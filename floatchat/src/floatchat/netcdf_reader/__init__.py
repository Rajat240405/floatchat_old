"""NetCDF Reader: extracts BGC variables from Argo profile files."""

from floatchat.netcdf_reader.base import AbstractNetCDFReader
from floatchat.netcdf_reader.bgc_reader import BGCNetCDFReader

__all__ = ["AbstractNetCDFReader", "BGCNetCDFReader"]
