"""txcelery
Copyright Sentimens Research Group, LLC
2014
MIT License

Module Contents:
    - DeferredTask
    - CeleryClient
"""
from functools import wraps

from twisted.internet.task import deferLater
from twisted.python.failure import Failure
from types import MethodType, FunctionType

from twisted.internet import defer, reactor
from celery import states
from celery.local import PromiseProxy
from celery.result import AsyncResult


class DeferredTask(defer.Deferred, object):
    """Subclass of `twisted.defer.Deferred` that wraps a
    `celery.local.PromiseProxy` (i.e. a "Celery task"), exposing the combined
    functionality of both classes.

    `DeferredTask` instances can be treated both like ordinary Deferreds and
    oridnary PromiseProxies.
    """

    def __init__(self, async_result, canceller=None):
        """Instantiate a `DeferredTask`.  See `help(DeferredTask)` for details
        pertaining to functionality.

        async_result : celery.result.AsyncResult
            AsyncResult to be monitored.  When completed or failed, the
            DeferredTask will callback or errback, respectively.

        canceller : None or callable
            See `help(twisted.internet.defer.Deferred)`
        """
        # Deferred is an old-style class
        defer.Deferred.__init__(self, canceller=canceller or self._canceller)

        self.task = async_result
        self._monitor_task()

    def _canceller(self):
        # from celery.task.control import revoke
        # revoke(task_id, terminate=True)
        self._d.cancel()

    def _monitor_task(self):
        """Wrapper that handles the actual asynchronous monitoring of the task
        state.
        """
        if self.task.state in states.UNREADY_STATES:
            reactor.callLater(0, self._monitor_task)
            return

        if self.task.state == 'SUCCESS':
            self.callback(self.task.result)
        elif self.task.state == 'FAILURE':
            self.errback(Failure(self.task.result))
        elif self.task.state == 'REVOKED':
            self.errback(
                Failure(defer.CancelledError('Task {0}'.format(self.task.id))))
        else:
            self.errback(ValueError(
                'Cannot respond to `{}` state'.format(self.task.state)
            ))


class CeleryClient(object):
    """Decorator class that wraps a celery task such that any methods
    returning an Celery `AsyncResult` instance are wrapped in a
    `DeferredTask` instance.

    Instances of `CeleryClient` expose all methods of the underlying Celery
    task.

    Usage:

        @CeleryClient
        @app.task
        def my_task():
            # ...

    Note:  The `@CeleryClient` decorator must be callsed __after__ the
           `@app.task` decorator, meaning that the former must be __above__
           the latter.
    """

    def __init__(self, fn):
        if not isinstance(fn, PromiseProxy):
            raise TypeError('Wrapped function must be a Celery task.')

        self._fn = fn

    def __repr__(self):
        s = self._fn.__repr__().strip('<>')
        return '<CeleryClient {s}>'.format(s=s)

    def __call__(self, *args, **kw):
        return self._fn(*args, **kw)

    def __getattr__(self, attr):
        attr = getattr(self._fn, attr)
        if isinstance(attr, MethodType) or isinstance(attr, FunctionType):
            return self._wrap(attr)
        return attr

    @staticmethod
    def _wrap(method):
        @wraps(method)
        def wrapper(*args, **kw):
            res = method(*args, **kw)
            if isinstance(res, AsyncResult):
                return DeferredTask(res)
            return res

        return wrapper


__all__ = [CeleryClient, DeferredTask]
