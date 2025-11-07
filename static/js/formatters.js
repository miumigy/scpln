(function (global) {
  'use strict';

  const PERCENT_KEYS = new Set([
    'fill_rate',
    'service_level',
    'on_time_rate',
    'capacity_util',
    'capacity_utilization',
  ]);
  const PERCENT_SUFFIXES = ['_rate', '_ratio', '_util', '_utilization'];

  function _toNumber(value) {
    if (value === null || value === undefined || value === '') return null;
    const num = Number(value);
    return Number.isFinite(num) ? num : null;
  }

  function _formatLocale(value, decimals, stripTrailing) {
    const opts = {
      minimumFractionDigits: stripTrailing ? 0 : decimals,
      maximumFractionDigits: decimals,
    };
    return value.toLocaleString(undefined, opts);
  }

  function formatNumber(value, decimals = 2, { stripTrailing = true } = {}) {
    const num = _toNumber(value);
    if (num === null) return '';
    const safeDecimals = Number.isInteger(decimals) ? Math.max(0, decimals) : 2;
    return _formatLocale(num, safeDecimals, stripTrailing);
  }

  function formatPercent(value, decimals = 2) {
    const num = _toNumber(value);
    if (num === null) return '';
    const scaled = num * 100;
    return _formatLocale(scaled, Math.max(0, decimals), false) + '%';
  }

  function isPercentKey(key) {
    if (!key) return false;
    const lowered = String(key).toLowerCase();
    if (PERCENT_KEYS.has(lowered)) return true;
    return PERCENT_SUFFIXES.some((suffix) => lowered.endsWith(suffix));
  }

  function formatMetric(value, key) {
    return isPercentKey(key) ? formatPercent(value) : formatNumber(value);
  }

  global.ScpFormat = {
    formatNumber,
    formatPercent,
    formatMetric,
    isPercentKey,
  };
})(window);
