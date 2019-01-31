# Licensed under a 3-clause BSD style license - see LICENSE.rst

from copy import deepcopy
from distutils.version import LooseVersion

import numpy as np

import astropy
from astropy.table import groups, QTable, Table
from astropy.time import Time, TimeDelta
from astropy import units as u
from astropy.units import Quantity

from .core import BaseTimeSeries

__all__ = ['TimeSeries']

ASTROPY_LT_32 = LooseVersion(astropy.__version__) < LooseVersion("3.2")


class TimeSeries(BaseTimeSeries):

    _require_time_column = False

    def __init__(self, data=None, time=None, time_delta=None, n_samples=None, **kwargs):
        """
        """

        super().__init__(data=data, **kwargs)

        # FIXME: this is because for some operations, an empty time series needs
        # to be created, then columns added one by one. We should check that
        # when columns are added manually, time is added first and is of the
        # right type.
        if data is None and time is None and time_delta is None:
            self._required_columns = ['time']
            return

        # First if time has been given in the table data, we should extract it
        # and treat it as if it had been passed as a keyword argument.

        if data is not None:
            if n_samples is not None:
                if n_samples != len(self):
                    raise TypeError("'n_samples' has been given both and it is not the "
                                    "same length as the input data.")
            else:
                n_samples = len(self)

        if 'time' in self.colnames:
            if time is None:
                time = self.columns['time']
                self.remove_column('time')
            else:
                raise TypeError("'time' has been given both in the table and as a keyword argument")

        if time is None:
            raise TypeError("'time' has not been specified")

        if not isinstance(time, Time):
            time = Time(time)

        if time_delta is not None and not isinstance(time_delta, (Quantity, TimeDelta)):
            raise TypeError("'time_delta' should be a Quantity or a TimeDelta")

        if isinstance(time_delta, TimeDelta):
            time_delta = time_delta.sec * u.s

        if time.isscalar:

            # We interpret this as meaning that time is that of the first
            # sample and that the interval is given by time_delta.

            if time_delta is None:
                raise TypeError("'time' is scalar, so 'time_delta' is required")

            if time_delta.isscalar:
                time_delta = np.repeat(time_delta, n_samples)

            time_delta = np.cumsum(time_delta)
            time_delta = np.roll(time_delta, 1)
            time_delta[0] = 0. * u.s

            time = time + time_delta

        else:

            if len(self.colnames) > 0 and len(time) != len(self):
                raise ValueError("Length of 'time' ({0}) should match "
                                 "data length ({1})".format(len(time), n_samples))

            if time_delta is not None:
                raise TypeError("'time_delta' should not be specified since "
                                "'time' is an array")

        self.add_column(time, index=0, name='time')

    @property
    def time(self):
        """
        The time values.
        """
        return self['time']

    def fold(self, period=None, midpoint_epoch=None):
        """
        Return a new TimeSeries folded with a period and midpoint epoch.

        Parameters
        ----------
        period : `~astropy.units.Quantity`
            The period to use for folding
        midpoint_epoch : `~astropy.time.Time`
            The time to use as the midpoint epoch, at which the relative
            time offset will be 0. Defaults to the first time in the time
            series.
        """

        folded = self.copy()
        folded.remove_column('time')

        if midpoint_epoch is None:
            midpoint_epoch = self.time[0]
        else:
            midpoint_epoch = Time(midpoint_epoch)

        period_sec = period.to_value(u.s)
        relative_time_sec = ((self.time - midpoint_epoch).sec + period_sec / 2) % period_sec - period_sec / 2

        folded_time = TimeDelta(relative_time_sec * u.s)

        folded.add_column(folded_time, name='time', index=0)

        return folded

    def __getitem__(self, item):
        if self._is_list_or_tuple_of_str(item):
            if 'time' not in item:
                out = QTable([self[x] for x in item],
                             meta=deepcopy(self.meta),
                             copy_indices=self._copy_indices)
                out._groups = groups.TableGroups(out, indices=self.groups._indices,
                                                 keys=self.groups._keys)
                return out
        return super().__getitem__(item)

    def add_columns(self, *args, **kwargs):
        result = super().add_columns(*args, **kwargs)
        if len(self.indices) == 0 and 'time' in self.colnames:
            self.add_index('time')
        return result

    @classmethod
    def from_pandas(self, df, time_scale='utc'):
        """
        Convert a :class:`~pandas.DataFrame` to a
        :class:`astropy.timeseries.TimeSeries`.

        Parameters
        ----------
        df : :class:`pandas.DataFrame`
            A pandas :class:`pandas.DataFrame` instance.
        time_scale : str
            The time scale to pass into `astropy.time.Time`.
            Defaults to ``UTC``.

        """
        from pandas import DataFrame, DatetimeIndex

        if not isinstance(df, DataFrame):
            raise TypeError("Input should be a pandas DataFrame")

        if not isinstance(df.index, DatetimeIndex):
            raise TypeError("DataFrame does not have a DatetimeIndex")

        time = Time(df.index, scale=time_scale)
        table = Table.from_pandas(df)

        return TimeSeries(time=time, data=table)

    def to_pandas(self):
        """
        Convert this :class:`~astropy.timeseries.TimeSeries` to a
        :class:`~pandas.DataFrame` with a :class:`~pandas.DatetimeIndex` index.

        Returns
        -------
        dataframe : :class:`pandas.DataFrame`
            A pandas :class:`pandas.DataFrame` instance
        """

        if ASTROPY_LT_32:
            # Extract table without time column
            table = self[[x for x in self.colnames if x != 'time']]
            df = Table(table).to_pandas()
            # Set index
            df.set_index(self.time.datetime64, inplace=True)
        else:
            df = Table(self).to_pandas(index='time')

        return df

    @classmethod
    def read(self, filename, format, time=None, time_column=None, time_format=None,
             time_delta=None, *args, **kwargs):
        """
        Read and parse a file and returns a `astropy.timeseries.sampled.TimeSeries`.

        This function provides the access to the astropy unified I/O layer.
        This allows easily reading a file in many supported data formats
        using syntax such as::

          >>> from astropy.timeseries.sampled import TimeSeries
          >>> dat = TimeSeries.read('table.dat', format='ascii', time_column='DATE')  # doctest: +SKIP

        See also: http://docs.astropy.org/en/stable/io/unified.html

        Parameters
        ----------
        filename: str
            File to parse.
        format : str
            File format specifier.
        time: str or list of str, optional
            Can be a `astropy.time.Time` parseable string or a list of said strings.
            This or ``time_column`` must be passed in.
        time_column: str, optional
            The name of the time column within the file.
            This or ``time`` must be passed in.
        time_format: str, optional
            Time format for the time_column.
        time_delta: float or list, optional
            The time step between each time index. If evenly sampled, you can specify
            one single time step. If arbitrarily sampled, you can pass in a list.
        *args : tuple, optional
            Positional arguments passed through to the data reader.
            If supplied, the first argument is the input filename.
        **kwargs : dict, optional
            Keyword arguments passed through to the data reader.

        Returns
        -------
        out : `astropy.timeseries.sampled.TimeSeries`
            TimeSeries corresponding to file contents.

        """

        table = Table.read(filename, format=format, *args, **kwargs)

        if time is None and time_column is None:
            raise ValueError("time and time_column are not set, please specify one of them.")

        if isinstance(time, list) and len(time) != len(table):
            raise ValueError("The time list is not the same length ({}) as the data ({}).".format(len(table), len(time)))

        if isinstance(time, str) and time_delta is None:
            raise ValueError("Please specify a time_delta for your time string.")

        if time_column is not None:
            if time_column not in table.colnames:
                raise ValueError("Time column {}, not found in the input data.".format(time_column))
            else:
                time = Time(table.columns[time_column])
                table.remove_column(time_column)
                if time_format is not None:
                    time.format = time_format

        return TimeSeries(time=time, data=table, time_delta=time_delta, n_samples=len(table))
