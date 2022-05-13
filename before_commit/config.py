# This file was picked from `cfgv` package
# (535635d9c2fe002860d13dda85e6effbfb2de0d1). The reason to copy it here is
# that it contains a bug on file handeling/loading. Because I can't contribute
# to nothing from @asottile and the file is under the same open-source license,
# I decided to just move it to here. I would upstream these changes, otherwise.
#
# Copyright (c) 2018 Anthony Sottile
# Copyright (c) 2022 Luís Ferreira
#
# Original source: https://github.com/asottile/cfgv
from __future__ import annotations

import collections
import contextlib
import os.path
import re
import sys
from typing import Any
from typing import Callable
from typing import Generator
from typing import Sequence


class ValidationError(ValueError):
    def __init__(
        self,
        error_msg: str | ValidationError,
        ctx: str | None = None,
    ) -> None:
        super().__init__(error_msg)
        self.error_msg = error_msg
        self.ctx = ctx

    def __str__(self) -> str:
        out = '\n'
        err = self
        while err.ctx is not None:
            out += f'==> {err.ctx}\n'
            if isinstance(err.error_msg, ValidationError):
                err = err.error_msg
            else:
                raise AssertionError(
                    'Non empty context should have parent ValidationError',
                )
        out += f'=====> {err.error_msg}'
        return out


MISSING = collections.namedtuple('Missing', ())()
type(MISSING).__repr__ = lambda self: 'MISSING'  # type: ignore


@contextlib.contextmanager
def validate_context(msg: str) -> Generator[None, None, None]:
    try:
        yield
    except ValidationError as e:
        _, _, tb = sys.exc_info()
        raise ValidationError(e, ctx=msg).with_traceback(tb) from None


@contextlib.contextmanager
def reraise_as(tp: type) -> Generator[None, None, None]:
    try:
        yield
    except ValidationError as e:
        _, _, tb = sys.exc_info()
        raise tp(e).with_traceback(tb) from None


def _dct_noop(self: Any, dct: dict[Any, Any]) -> None:
    pass


def _check_optional(self: Any, dct: dict[Any, Any]) -> None:
    if self.key not in dct:
        return
    with validate_context(f'At key: {self.key}'):
        self.check_fn(dct[self.key])


def _apply_default_optional(self: Any, dct: dict[Any, Any]) -> None:
    dct.setdefault(self.key, self.default)


def _remove_default_optional(self: Any, dct: dict[Any, Any]) -> None:
    if dct.get(self.key, MISSING) == self.default:
        del dct[self.key]


def _require_key(self: Any, dct: dict[Any, Any]) -> None:
    if self.key not in dct:
        raise ValidationError(f'Missing required key: {self.key}')


def _check_required(self: Any, dct: dict[Any, Any]) -> None:
    _require_key(self, dct)
    _check_optional(self, dct)


@property  # type: ignore
def _check_fn_recurse(self: Any) -> Callable[[Any], None]:
    def check_fn(val: Any) -> None:
        validate(val, self.schema)
    return check_fn


def _apply_default_required_recurse(self: Any, dct: dict[Any, Any]) -> None:
    dct[self.key] = apply_defaults(dct[self.key], self.schema)


def _remove_default_required_recurse(self: Any, dct: dict[Any, Any]) -> None:
    dct[self.key] = remove_defaults(dct[self.key], self.schema)


def _apply_default_optional_recurse(self: Any, dct: dict[Any, Any]) -> None:
    if self.key not in dct:
        _apply_default_optional(self, dct)
    _apply_default_required_recurse(self, dct)


def _remove_default_optional_recurse(self: Any, dct: dict[Any, Any]) -> None:
    if self.key in dct:
        _remove_default_required_recurse(self, dct)
        _remove_default_optional(self, dct)


def _get_check_conditional(inner: Callable[..., Any]) -> Callable[..., Any]:
    def _check_conditional(self: Any, dct: dict[Any, Any]) -> None:
        if dct.get(self.condition_key, MISSING) == self.condition_value:
            inner(self, dct)
        elif (
                self.condition_key in dct and
                self.ensure_absent and self.key in dct
        ):
            if hasattr(self.condition_value, 'describe_opposite'):
                explanation = self.condition_value.describe_opposite()
            else:
                explanation = f'is not {self.condition_value!r}'
            raise ValidationError(
                f'Expected {self.key} to be absent when {self.condition_key} '
                f'{explanation}, found {self.key}: {dct[self.key]!r}',
            )
    return _check_conditional


def _apply_default_conditional_optional(
        self: Any,
        dct: dict[Any, Any],
) -> None:
    if dct.get(self.condition_key, MISSING) == self.condition_value:
        _apply_default_optional(self, dct)


def _remove_default_conditional_optional(
        self: Any,
        dct: dict[Any, Any],
) -> None:
    if dct.get(self.condition_key, MISSING) == self.condition_value:
        _remove_default_optional(self, dct)


def _apply_default_conditional_recurse(
        self: Any,
        dct: dict[Any, Any],
) -> None:
    if dct.get(self.condition_key, MISSING) == self.condition_value:
        _apply_default_required_recurse(self, dct)


def _remove_default_conditional_recurse(
        self: Any,
        dct: dict[Any, Any],
) -> None:
    if dct.get(self.condition_key, MISSING) == self.condition_value:
        _remove_default_required_recurse(self, dct)


def _no_additional_keys_check(
        self: Any,
        dct: dict[Any, Any],
) -> None:
    extra = sorted(set(dct) - set(self.keys))
    if extra:
        extra_s = ', '.join(str(x) for x in extra)
        keys_s = ', '.join(str(x) for x in self.keys)
        raise ValidationError(
            f'Additional keys found: {extra_s}.  '
            f'Only these keys are allowed: {keys_s}',
        )


def _warn_additional_keys_check(
        self: Any,
        dct: dict[Any, Any],
) -> None:
    extra = sorted(set(dct) - set(self.keys))
    if extra:
        self.callback(extra, self.keys, dct)


Required = collections.namedtuple('Required', ('key', 'check_fn'))
Required.check = _check_required  # type: ignore
Required.apply_default = _dct_noop  # type: ignore
Required.remove_default = _dct_noop  # type: ignore
RequiredRecurse = collections.namedtuple('RequiredRecurse', ('key', 'schema'))
RequiredRecurse.check = _check_required  # type: ignore
RequiredRecurse.check_fn = _check_fn_recurse  # type: ignore
RequiredRecurse.apply_default = _apply_default_required_recurse  # type: ignore
RequiredRecurse.remove_default = _remove_default_required_recurse  # type: ignore # noqa: E501
Optional = collections.namedtuple('Optional', ('key', 'check_fn', 'default'))
Optional.check = _check_optional  # type: ignore
Optional.apply_default = _apply_default_optional  # type: ignore
Optional.remove_default = _remove_default_optional  # type: ignore
OptionalRecurse = collections.namedtuple(
    'OptionalRecurse', ('key', 'schema', 'default'),
)
OptionalRecurse.check = _check_optional  # type: ignore
OptionalRecurse.check_fn = _check_fn_recurse  # type: ignore
OptionalRecurse.apply_default = _apply_default_optional_recurse  # type: ignore
OptionalRecurse.remove_default = _remove_default_optional_recurse  # type: ignore # noqa: E501
OptionalNoDefault = collections.namedtuple(
    'OptionalNoDefault', ('key', 'check_fn'),
)
OptionalNoDefault.check = _check_optional  # type: ignore
OptionalNoDefault.apply_default = _dct_noop  # type: ignore
OptionalNoDefault.remove_default = _dct_noop  # type: ignore
Conditional = collections.namedtuple(
    'Conditional',
    ('key', 'check_fn', 'condition_key', 'condition_value', 'ensure_absent'),
)
Conditional.__new__.__defaults__ = (False,)  # type: ignore
Conditional.check = _get_check_conditional(_check_required)  # type: ignore
Conditional.apply_default = _dct_noop  # type: ignore
Conditional.remove_default = _dct_noop  # type: ignore
ConditionalOptional = collections.namedtuple(
    'ConditionalOptional',
    (
        'key', 'check_fn', 'default', 'condition_key', 'condition_value',
        'ensure_absent',
    ),
)
ConditionalOptional.__new__.__defaults__ = (False,)  # type: ignore
ConditionalOptional.check = _get_check_conditional(_check_optional)  # type: ignore # noqa: E501
ConditionalOptional.apply_default = _apply_default_conditional_optional  # type: ignore # noqa: E501
ConditionalOptional.remove_default = _remove_default_conditional_optional  # type: ignore # noqa: E501
ConditionalRecurse = collections.namedtuple(
    'ConditionalRecurse',
    ('key', 'schema', 'condition_key', 'condition_value', 'ensure_absent'),
)
ConditionalRecurse.__new__.__defaults__ = (False,)  # type: ignore
ConditionalRecurse.check = _get_check_conditional(_check_required)  # type: ignore # noqa: E501
ConditionalRecurse.check_fn = _check_fn_recurse  # type: ignore
ConditionalRecurse.apply_default = _apply_default_conditional_recurse  # type: ignore # noqa: E501
ConditionalRecurse.remove_default = _remove_default_conditional_recurse  # type: ignore # noqa: E501
NoAdditionalKeys = collections.namedtuple('NoAdditionalKeys', ('keys',))
NoAdditionalKeys.check = _no_additional_keys_check  # type: ignore
NoAdditionalKeys.apply_default = _dct_noop  # type: ignore
NoAdditionalKeys.remove_default = _dct_noop  # type: ignore
WarnAdditionalKeys = collections.namedtuple(
    'WarnAdditionalKeys', ('keys', 'callback'),
)
WarnAdditionalKeys.check = _warn_additional_keys_check  # type: ignore
WarnAdditionalKeys.apply_default = _dct_noop  # type: ignore
WarnAdditionalKeys.remove_default = _dct_noop  # type: ignore


class Map(collections.namedtuple('Map', ('object_name', 'id_key', 'items'))):
    __slots__ = ()

    def __new__(
            cls,
            object_name: str,
            id_key: str | None,
            *items: Any,
    ) -> Any:
        return super().__new__(cls, object_name, id_key, items)

    def check(self, v: Any) -> None:
        if not isinstance(v, dict):
            raise ValidationError(
                f'Expected a {self.object_name} map but got a '
                f'{type(v).__name__}',
            )
        if self.id_key is None:
            context = f'At {self.object_name}()'
        else:
            key_v_s = v.get(self.id_key, MISSING)
            context = f'At {self.object_name}({self.id_key}={key_v_s!r})'
        with validate_context(context):
            for item in self.items:
                item.check(v)

    def apply_defaults(self, v: Any) -> Any:
        ret = v.copy()
        for item in self.items:
            item.apply_default(ret)
        return ret

    def remove_defaults(self, v: Any) -> Any:
        ret = v.copy()
        for item in self.items:
            item.remove_default(ret)
        return ret


class Array(collections.namedtuple('Array', ('of', 'allow_empty'))):
    __slots__ = ()

    def __new__(cls, of: Any, allow_empty: bool = True) -> Any:
        return super().__new__(cls, of=of, allow_empty=allow_empty)

    def check(self, v: Sequence[Any]) -> None:
        check_array(check_any)(v)
        if not self.allow_empty and not v:
            raise ValidationError(
                f"Expected at least 1 '{self.of.object_name}'",
            )
        for val in v:
            validate(val, self.of)

    def apply_defaults(self, v: Sequence[Any]) -> Sequence[Any]:
        return [apply_defaults(val, self.of) for val in v]

    def remove_defaults(self, v: Sequence[Any]) -> Sequence[Any]:
        return [remove_defaults(val, self.of) for val in v]


class Not(collections.namedtuple('Not', ('val',))):
    __slots__ = ()

    def describe_opposite(self) -> str:
        return f'is {self.val!r}'

    def __eq__(self, other: Any) -> bool:
        return other is not MISSING and other != self.val


class NotIn(collections.namedtuple('NotIn', ('values',))):
    __slots__ = ()

    def __new__(cls, *values: Any) -> Any:
        return super().__new__(cls, values=values)

    def describe_opposite(self) -> str:
        return f'is any of {self.values!r}'

    def __eq__(self, other: Any) -> bool:
        return other is not MISSING and other not in self.values


class In(collections.namedtuple('In', ('values',))):
    __slots__ = ()

    def __new__(cls, *values: Any) -> Any:
        return super().__new__(cls, values=values)

    def describe_opposite(self) -> str:
        return f'is not any of {self.values!r}'

    def __eq__(self, other: Any) -> bool:
        return other is not MISSING and other in self.values


def check_any(_: Any) -> None:
    pass


def check_type(tp: type, typename: str | None = None) -> Callable[..., None]:
    def check_type_fn(v: Any) -> None:
        if not isinstance(v, tp):
            typename_s = typename or tp.__name__
            raise ValidationError(
                f'Expected {typename_s} got {type(v).__name__}',
            )
    return check_type_fn


check_bool = check_type(bool)
check_bytes = check_type(bytes)
check_int = check_type(int)
check_string = check_type(str, typename='string')
check_text = check_type(str, typename='text')


def check_one_of(possible: Any) -> Callable[[Any], None]:
    def check_one_of_fn(v: Any) -> None:
        if v not in possible:
            possible_s = ', '.join(str(x) for x in sorted(possible))
            raise ValidationError(
                f'Expected one of {possible_s} but got: {v!r}',
            )
    return check_one_of_fn


def check_regex(v: str) -> None:
    try:
        re.compile(v)
    except re.error:
        raise ValidationError(f'{v!r} is not a valid python regex')


def check_array(inner_check: Callable[[Any], None]) -> Callable[[Any], None]:
    def check_array_fn(v: Any) -> None:
        if not isinstance(v, (list, tuple)):
            raise ValidationError(
                f'Expected array but got {type(v).__name__!r}',
            )

        for i, val in enumerate(v):
            with validate_context(f'At index {i}'):
                inner_check(val)
    return check_array_fn


def check_and(*fns: Callable[[Any], None]) -> Callable[[Any], None]:
    def check(v: Any) -> None:
        for fn in fns:
            fn(v)
    return check


def validate(v: Any, schema: Any) -> Any:
    schema.check(v)
    return v


def apply_defaults(v: Any, schema: Any) -> Any:
    return schema.apply_defaults(v)


def remove_defaults(v: Any, schema: Any) -> Any:
    return schema.remove_defaults(v)


def load_from_filename(
        filename: str,
        schema: Any,
        load_strategy: Callable[[str | bytes], Any],
        exc_tp: type = ValidationError,
) -> Any:
    with reraise_as(exc_tp):
        if (not os.path.isfile(filename) and not os.path.exists(filename)) \
                or os.path.isdir(filename):
            raise ValidationError(f'{filename} is not a file')

        with validate_context(f'File {filename}'):
            try:
                with open(filename, encoding='utf-8') as f:
                    contents = f.read()
            except UnicodeDecodeError as e:
                raise ValidationError(str(e))

            try:
                data = load_strategy(contents)
            except Exception as e:
                raise ValidationError(str(e))

            validate(data, schema)
            return apply_defaults(data, schema)
