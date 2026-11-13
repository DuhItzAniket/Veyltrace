"""Dataset fetchers behind `veyltrace data fetch` (entry-point group `veyltrace.fetchers`; 01 §3.11).

The only network code of the engines (02 §6.1, §9): stdlib `urllib.request`, and nothing outside
this subpackage imports it (isolation test). Import-free, so naming the package loads nothing.
"""
