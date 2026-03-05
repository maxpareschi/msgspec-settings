"""CLI-backed data source implementation."""

import contextvars
import sys
from typing import Any, Literal, get_args, get_origin

import msgspec
import rich_click as click
from msgspec.structs import fields as struct_fields

from ..base import DataSource
from ..mapping import flatten_model_fields_with_alias
from ..merge import dedupe_keep_order, set_nested
from ..typing import (
    _COERCE_FAILED,
    coerce_env_value,
    get_struct_subtype,
    try_json_decode,
    unwrap_annotated,
)


def _python_type_to_click(field_type: Any) -> dict[str, Any]:
    """Map a Python annotation to click option kwargs.

    Args:
        field_type: Field annotation to map.

    Returns:
        Option kwargs dictionary. Bool fields return
        ``{"is_bool_flag": True}``.
    """
    field_type = unwrap_annotated(field_type)
    origin = get_origin(field_type)
    if origin is not None:
        args = get_args(field_type)

        if origin is Literal:
            if all(isinstance(item, str) for item in args):
                return {"type": click.Choice([str(item) for item in args])}
            return {"type": click.STRING}

        non_none = [item for item in args if item is not type(None)]
        has_none = len(non_none) != len(args)
        if has_none and len(non_none) == 1:
            return _python_type_to_click(non_none[0])

        if non_none:
            return {"type": click.STRING}

    if get_struct_subtype(field_type) is not None:
        return {"type": click.STRING}

    if field_type is bool:
        return {"is_bool_flag": True}

    type_map: dict[type, Any] = {
        str: click.STRING,
        int: click.INT,
        float: click.FLOAT,
    }
    return {"type": type_map.get(field_type, click.STRING)}


def _make_flag_name(dotted_path: str, kebab_case: bool = True) -> str:
    """Build a long option flag from a dotted field path.

    Args:
        dotted_path: Canonical dotted field path.
        kebab_case: Whether to render separators as dashes.

    Returns:
        Long option string prefixed with ``--``.
    """
    if kebab_case:
        return "--" + dotted_path.replace(".", "-").replace("_", "-")
    return "--" + dotted_path


def _assign_short(long_flag: str, reserved: set[str], assigned: set[str]) -> str | None:
    """Assign a non-conflicting short option token.

    Args:
        long_flag: Long option declaration.
        reserved: Reserved short tokens.
        assigned: Already-assigned short tokens.

    Returns:
        Chosen short token without leading ``-``, or ``None``.
    """
    name = long_flag[2:] if long_flag.startswith("--") else long_flag
    if not name:
        return None

    for length in range(1, len(name) + 1):
        candidate = name[:length].replace(".", "-").replace("_", "-")
        if candidate in reserved or candidate in assigned:
            continue
        assigned.add(candidate)
        return candidate
    return None


class CliSource(DataSource):
    """Load configuration values from command-line arguments.

    Attributes:
        cli_args: Optional argument list. Uses ``sys.argv[1:]`` when unset.
        kebab_case: Use kebab-case long flags when true.
        theme: Rich-click theme name passed via context settings.
    """

    cli_args: list[str] | None = None
    kebab_case: bool = True
    theme: str = "cargo-slim"

    @property
    def cli_extra_args(self) -> list[str]:
        """Return uncaptured CLI args from the last ``load`` call.

        Returns:
            Unknown/extra arguments from the last parse.
        """
        extra_args_var = getattr(self, "__cli_extra_args_var__", None)
        if extra_args_var is None:
            return []
        return list(extra_args_var.get())

    def load(self, model: type[msgspec.Struct] | None = None) -> dict[str, Any]:
        """Parse command-line options into model-shaped nested data.

        Args:
            model: Target model used to generate options and coerce values.

        Returns:
            Nested mapping of explicitly provided values.

        Raises:
            TypeError: On generated option-name collisions.
            click.BadParameter: On invalid literal coercion.
            SystemExit: For help/exit pathways raised by click.
        """
        if model is None:
            return {}

        flat_with_alias = flatten_model_fields_with_alias(model)
        if not flat_with_alias:
            return {}

        flat_fields: dict[str, Any] = {
            dotted_path: field_info[1]
            for dotted_path, field_info in flat_with_alias.items()
        }

        params: list[click.Parameter] = []
        param_to_path: dict[str, str] = {}
        decl_to_path: dict[str, str] = {}
        bool_neg_map: dict[str, str] = {}
        json_struct_params: dict[str, str] = {}
        use_kebab = self.kebab_case

        def _register_decl(decl: str, dotted_path: str) -> None:
            existing_path = decl_to_path.get(decl)
            if existing_path is not None and existing_path != dotted_path:
                raise TypeError(
                    f"CLI option declaration collision: '{existing_path}' and "
                    f"'{dotted_path}' both map to '{decl}'"
                )
            decl_to_path[decl] = dotted_path

        # Collect top-level Struct fields to expose JSON options.
        struct_field_names: dict[str, tuple[str, str]] = {}
        for field_info in struct_fields(model):
            if get_struct_subtype(field_info.type) is None:
                continue
            encode_name = getattr(field_info, "encode_name", field_info.name)
            if not isinstance(encode_name, str) or not encode_name:
                encode_name = field_info.name
            struct_field_names[field_info.name] = (field_info.name, encode_name)

        emitted_json_opts: set[str] = set()

        ctx_settings: dict[str, Any] = {
            "help_option_names": ["-h", "--help", "-?"],
            "ignore_unknown_options": True,
            "allow_extra_args": True,
            "rich_help_config": {
                "theme": self.theme,
                "enable_theme_env_var": False,
            },
        }

        reserved_short: set[str] = set(
            item.replace("-", "") for item in ctx_settings["help_option_names"]
        )
        assigned_short: set[str] = set()

        for dotted_path, field_meta in flat_with_alias.items():
            alias_path, field_type = field_meta
            top_field = dotted_path.split(".")[0]

            if top_field in struct_field_names and top_field not in emitted_json_opts:
                emitted_json_opts.add(top_field)
                _, top_alias = struct_field_names[top_field]

                top_long_flags = [_make_flag_name(top_field, kebab_case=use_kebab)]
                alias_top_flag = _make_flag_name(top_alias, kebab_case=use_kebab)
                if alias_top_flag not in top_long_flags:
                    top_long_flags.append(alias_top_flag)
                top_long_flags = dedupe_keep_order(top_long_flags)

                json_param_name = top_field.replace(".", "_").replace("-", "_")
                json_struct_params[json_param_name] = top_field
                json_decls = list(top_long_flags)
                if not use_kebab:
                    json_decls.append(json_param_name)
                json_decls = dedupe_keep_order(json_decls)

                short = _assign_short(top_long_flags[0], reserved_short, assigned_short)
                if short is not None:
                    json_decls.insert(0, "-" + short)

                for decl in json_decls:
                    if decl.startswith("-"):
                        _register_decl(decl, top_field)

                params.append(
                    click.Option(
                        param_decls=json_decls,
                        type=click.STRING,
                        help="JSON string",
                    )
                )

            long_flags = [_make_flag_name(dotted_path, kebab_case=use_kebab)]
            alias_flag = _make_flag_name(alias_path, kebab_case=use_kebab)
            if alias_flag not in long_flags:
                long_flags.append(alias_flag)
            long_flags = dedupe_keep_order(long_flags)

            param_name = dotted_path.replace(".", "_").replace("-", "_")
            existing_path = param_to_path.get(param_name)
            if existing_path is not None and existing_path != dotted_path:
                raise TypeError(
                    f"CLI option name collision: '{existing_path}' and "
                    f"'{dotted_path}' both map to '{param_name}'"
                )
            param_to_path[param_name] = dotted_path

            for decl in long_flags:
                _register_decl(decl, dotted_path)

            click_kwargs = _python_type_to_click(field_type)
            is_bool_flag = bool(click_kwargs.pop("is_bool_flag", False))

            if is_bool_flag:
                pos_decls = list(long_flags)
                if not use_kebab:
                    pos_decls.append(param_name)
                if "." not in dotted_path:
                    short = _assign_short(long_flags[0], reserved_short, assigned_short)
                    if short is not None:
                        pos_decls.insert(0, "-" + short)
                pos_decls = dedupe_keep_order(pos_decls)
                params.append(
                    click.Option(
                        param_decls=pos_decls,
                        is_flag=True,
                        flag_value=True,
                    )
                )

                neg_param_name = "no_" + param_name
                existing_neg = bool_neg_map.get(neg_param_name)
                if existing_neg is not None and existing_neg != dotted_path:
                    raise TypeError(
                        f"CLI bool negation collision: '{existing_neg}' and "
                        f"'{dotted_path}' both map to '{neg_param_name}'"
                    )
                bool_neg_map[neg_param_name] = dotted_path

                neg_decls = [f"--no-{flag[2:]}" for flag in long_flags]
                if not use_kebab:
                    neg_decls.append(neg_param_name)
                neg_decls = dedupe_keep_order(neg_decls)
                for decl in neg_decls:
                    _register_decl(decl, dotted_path)
                params.append(
                    click.Option(
                        param_decls=neg_decls,
                        is_flag=True,
                        flag_value=True,
                        hidden=True,
                    )
                )
                continue

            click_kwargs.setdefault("default", None)
            click_kwargs["required"] = False

            decls = list(long_flags)
            if not use_kebab:
                decls.append(param_name)
            if "." not in dotted_path:
                short = _assign_short(long_flags[0], reserved_short, assigned_short)
                if short is not None:
                    decls.insert(0, "-" + short)
            decls = dedupe_keep_order(decls)

            help_text = click_kwargs.pop("help", None) or ""
            params.append(
                click.Option(
                    param_decls=decls,
                    help=help_text or None,
                    **click_kwargs,
                )
            )

        command_name = getattr(model, "__name__", "cli").lower()

        epilog_parts: list[str] = []
        if bool_neg_map:
            epilog_parts.append(
                "Untyped flags (toggles) can be negated with the --no- prefix "
                "(e.g. --no-debug)."
            )
        if json_struct_params:
            epilog_parts.append(
                "Nested options accept a JSON string "
                '(e.g. --log \'{"level": "DEBUG"}\').'
            )

        command = click.RichCommand(
            name=command_name,
            params=params,
            context_settings=ctx_settings,
            epilog="\n\n".join(epilog_parts) if epilog_parts else None,
        )

        args = list(self.cli_args) if self.cli_args is not None else sys.argv[1:]

        try:
            ctx: click.Context = command.make_context(command_name, list(args))
        except click.exceptions.Exit as exc:
            raise SystemExit(getattr(exc, "code", 0)) from None

        extra_args_var = getattr(self, "__cli_extra_args_var__", None)
        if extra_args_var is None:
            extra_args_var = contextvars.ContextVar(
                f"cli_extra_args_{id(self)}", default=()
            )
            self.__cli_extra_args_var__ = extra_args_var
        extra_args_var.set(tuple(ctx.args))

        raw_values: dict[str, Any] = ctx.params
        result: dict[str, Any] = {}

        # Pass 1: struct JSON options.
        for param_name, value in raw_values.items():
            if value is None or param_name not in json_struct_params:
                continue
            source = ctx.get_parameter_source(param_name)
            if source is not None and source != click.core.ParameterSource.COMMANDLINE:
                continue
            decoded = try_json_decode(value)
            if decoded is not _COERCE_FAILED and isinstance(decoded, dict):
                set_nested(result, json_struct_params[param_name], decoded)

        # Pass 2: scalar fields + bool negations (override JSON subkeys).
        for param_name, value in raw_values.items():
            if value is None or param_name in json_struct_params:
                continue
            source = ctx.get_parameter_source(param_name)
            if source is not None and source != click.core.ParameterSource.COMMANDLINE:
                continue

            neg_path = bool_neg_map.get(param_name)
            if neg_path is not None:
                set_nested(result, neg_path, False)
                continue

            dotted_path = param_to_path.get(param_name)
            if dotted_path is None:
                continue

            field_type = flat_fields.get(dotted_path)
            if field_type is not None and isinstance(value, str):
                unwrapped = unwrap_annotated(field_type)
                coerced = coerce_env_value(value, field_type)
                if coerced is _COERCE_FAILED and get_origin(unwrapped) is Literal:
                    allowed = ", ".join(repr(item) for item in get_args(unwrapped))
                    raise click.BadParameter(
                        f"invalid literal value {value!r}; allowed values: {allowed}",
                        param_hint=_make_flag_name(dotted_path, kebab_case=use_kebab),
                    )
                if coerced is not _COERCE_FAILED:
                    value = coerced

            set_nested(result, dotted_path, value)

        return result
