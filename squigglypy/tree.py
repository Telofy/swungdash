from __future__ import annotations

import operator
from copy import copy
from itertools import chain
from collections.abc import Callable
from dataclasses import replace
from functools import partialmethod
from random import sample
from typing import Any, Hashable, Iterable, List, Optional, Sequence, Tuple, Union
from enum import Enum

import numpy as np

from .context import CacheKey, Context


class Empty(Enum):
    # See https://www.python.org/dev/peps/pep-0484/#support-for-singleton-types-in-unions
    empty = None


_empty = Empty.empty


class Resolveable:
    def __invert__(self):
        return self._resolve()

    def _resolve(self) -> Union[Any, Iterable[Any], Empty]:
        raise NotImplementedError

    @property
    def cache_key(self) -> Hashable:
        raise NotImplementedError


class Value(Resolveable):
    constant: Optional[bool] = None  # Whether the value depends on independent variables
    name: Optional[str] = None

    def __init__(
        self,
        value: Union[float, Resolveable, Empty],
        constant: Optional[bool] = None,
        name: Optional[str] = None,
    ):
        self.value = value
        self.constant = constant
        self.name = name

    def __repr__(self):
        if self.name:
            return self.name
        return str(self.value)

    @property
    def cache_key(self):
        if isinstance(self.value, Resolveable):
            return self.value.cache_key
        return self.value

    def _resolve(self):
        if isinstance(self.value, Resolveable):
            return ~self.value
        return self.value

    def _operation(
        self,
        function: Callable[..., Union[float, bool]],
        other: Union[float, Value, Empty] = _empty,
        reverse: bool = False,
    ):
        if not isinstance(other, Resolveable):
            other = Value(other)
        if reverse:
            assert other.value is not _empty
            return Value(Operation(function, other, self))
        return Value(Operation(function, self, other))

    __neg__ = partialmethod(_operation, operator.neg)
    __pos__ = partialmethod(_operation, operator.pos)
    __abs__ = partialmethod(_operation, operator.abs)

    __add__ = partialmethod(_operation, operator.add)
    __floordiv__ = partialmethod(_operation, operator.floordiv)
    __mod__ = partialmethod(_operation, operator.mod)
    __mul__ = partialmethod(_operation, operator.mul)
    __pow__ = partialmethod(_operation, operator.pow)
    __sub__ = partialmethod(_operation, operator.sub)
    __truediv__ = partialmethod(_operation, operator.truediv)

    __radd__ = partialmethod(_operation, operator.add, reverse=True)
    __rfloordiv__ = partialmethod(_operation, operator.floordiv, reverse=True)
    __rmod__ = partialmethod(_operation, operator.mod, reverse=True)
    __rmul__ = partialmethod(_operation, operator.mul, reverse=True)
    __rpow__ = partialmethod(_operation, operator.pow, reverse=True)
    __rsub__ = partialmethod(_operation, operator.sub, reverse=True)
    __rtruediv__ = partialmethod(_operation, operator.truediv, reverse=True)

    # TODO: Decide whether the implementation of the below six methods is really what we want
    __lt__ = partialmethod(_operation, operator.lt)
    __le__ = partialmethod(_operation, operator.le)
    __eq__ = partialmethod(_operation, operator.eq)  # type: ignore
    __ne__ = partialmethod(_operation, operator.ne)  # type: ignore
    __ge__ = partialmethod(_operation, operator.ge)
    __gt__ = partialmethod(_operation, operator.gt)


class Operation(Resolveable):
    FORMATS = {
        operator.neg: "-{this}",
        operator.pos: "{this}",
        operator.abs: "abs({this})",
        operator.add: "({this} + {other})",
        operator.floordiv: "({this} // {other})",
        operator.mod: "({this} % {other})",
        operator.mul: "({this} * {other})",
        operator.pow: "({this} ** {other})",
        operator.sub: "({this} - {other})",
        operator.truediv: "({this} / {other})",
        operator.lt: "({this} < {other})",
        operator.le: "({this} <= {other})",
        operator.eq: "({this} == {other})",
        operator.ne: "({this} != {other})",
        operator.ge: "({this} >= {other})",
        operator.gt: "({this} > {other})",
    }

    def __init__(
        self,
        function: Callable[..., Any],
        this: Value,
        other: Value = Value(_empty),
    ):
        self.function = function
        self.this = this
        self.other = other

    @property
    def cache_key(self):
        this_key = self.this.cache_key
        other_key = self.other.cache_key
        return CacheKey(function=self.function, nested=(this_key, other_key))

    def __repr__(self):
        if self.function in self.FORMATS:
            if self.other is _empty:
                return self.FORMATS[self.function].format(this=self.this)
            return self.FORMATS[self.function].format(this=self.this, other=self.other)
        return f"{type(self).__name__}({self.function.__name__}, {self.this}, {self.other})"

    def _resolve(self):
        this, other = ~self.this, ~self.other
        if other is _empty:
            return self.function(this)
        return self.function(this, other)


class Distribution(Value):
    constant = True

    def __init__(
        self,
        function: Callable[..., Iterable[float]],
        *args: float,
        name: Optional[str] = None,
        **kwargs: Empty,
    ):  # pylint: disable=super-init-not-called
        self.function = function
        self.name = name
        self.args = args
        self.kwargs = kwargs

    def __repr__(self):
        if self.name:
            return self.name
        name = self.function.__name__
        args = ", ".join(map(str, self.args))
        kwargs = ", ".join(f"{key}={value}" for key, value in self.kwargs.items())
        return f'{name}({", ".join(part for part in (args, kwargs) if part)})'

    @property
    def cache_key(self):
        with Context() as context:
            return CacheKey(
                sample_count=context.sample_count,
                function=self.function,
                args=self.args,
                kwargs=tuple(sorted(self.kwargs.items())),
            )

    def _resolve(self):
        with Context() as context:
            if self.cache_key in context.cache:
                return context.cache[self.cache_key]
            value = self.function(*self.args, size=context.sample_count, **self.kwargs)
            context.cache[self.cache_key] = value
            return value


class Mixture(Value):
    def __init__(
        self, values: Sequence[Value], name: Optional[str] = None
    ):  # pylint: disable=super-init-not-called
        self.values = values
        self.name = name

    def __repr__(self):
        if self.name:
            return self.name
        return f"{type(self).__name__}({self.values})"

    @property
    def cache_key(self):
        with Context() as context:
            return CacheKey(
                sample_count=context.sample_count,
                nested=tuple(replace(value.cache_key, sample_count=None) for value in self.values),
            )

    @staticmethod
    def _sample(*values: Value):
        with Context() as context:
            remainder = context.sample_count % len(values)
            sample_counts = [context.sample_count // len(values)] * len(values)
        sample_counts = [
            sample_count + int(i < remainder) for i, sample_count in enumerate(sample_counts)
        ]
        sample_counts = sample(sample_counts, len(sample_counts))  # Shuffling
        samples = []
        for value, sample_count in zip(values, sample_counts):
            with Context(sample_count=sample_count):
                samples.append(~value)
        return np.concatenate(samples)

    def _resolve(self):
        with Context() as context:
            if self.cache_key in context.cache:
                return context.cache[self.cache_key]
            value = self._sample(*self.values)
            context.cache[self.cache_key] = value
            return value


_tracer: Value = Value(0, name="x")


def _mark_constancy(tree: Union[float, Value]) -> bool:
    if tree is _tracer:
        return False
    if not isinstance(tree, Value):
        return True
    if tree.constant is not None:
        return tree.constant
    if isinstance(tree, Mixture):
        for value in tree.values:
            value.constant = _mark_constancy(value)
        return all(value.constant for value in tree.values)
    if isinstance(tree.value, Operation):
        tree.value.this.constant = _mark_constancy(tree.value.this)
        if tree.value.other is _empty:
            return tree.value.this.constant
        tree.value.other.constant = _mark_constancy(tree.value.other)
        return tree.value.this.constant and tree.value.other.constant
    if isinstance(tree.value, Value):
        tree.value.constant = _mark_constancy(tree.value)
        return tree.value.constant
    return True


def mark_constancy(tree: Union[float, Value]):
    if not isinstance(tree, Value):
        return tree
    tree.constant = _mark_constancy(tree)
    return tree


def _bfs(tree: Union[float, Resolveable, Empty]) -> List[Value]:
    if isinstance(tree, Distribution):
        return [tree]
    if isinstance(tree, Mixture):
        nested = [_bfs(value_) for value_ in tree.values]
        return [tree] + list(chain.from_iterable(nested))  # type: ignore
    if isinstance(tree, Value):
        return [tree] + _bfs(tree.value)
    if isinstance(tree, Operation):
        return _bfs(tree.this) + _bfs(tree.other)
    return []


def bfs(model: Union[Callable[..., float], Callable[..., Value]]) -> Tuple[List[Value], Value]:
    tracer = copy(_tracer)
    tree = model(_tracer)
    tree = mark_constancy(tree)  # For visualization
    return _bfs(tree), tracer


def as_model(part: Value, tracer: Value):
    def model(x: float):
        tracer.value = x
        return part

    return model