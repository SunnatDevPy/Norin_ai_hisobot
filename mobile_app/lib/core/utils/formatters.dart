import 'package:intl/intl.dart';

String formatUzs(num? value, {bool withCurrency = true}) {
  final val = (value ?? 0).round();
  final formatted = NumberFormat('#,##0', 'en_US').format(val).replaceAll(',', ' ');
  return withCurrency ? "$formatted so'm" : formatted;
}

String formatCompactUzs(num? value) {
  final v = (value ?? 0).toDouble();
  final abs = v.abs();
  final sign = v < 0 ? '-' : '';
  if (abs >= 1e9) {
    return '$sign${(abs / 1e9).toStringAsFixed(1)} mlrd';
  }
  if (abs >= 1e6) {
    final m = abs / 1e6;
    return '$sign${m >= 10 ? m.toStringAsFixed(0) : m.toStringAsFixed(1)} mln';
  }
  if (abs >= 1e3) {
    return '$sign${(abs / 1e3).toStringAsFixed(0)}k';
  }
  return '$sign${abs.round()}';
}

String formatKg(num? value, {String unit = 'kg'}) {
  final v = (value ?? 0).toDouble();
  final clean = (v == v.roundToDouble())
      ? v.round().toString()
      : v.toStringAsFixed(3).replaceFirst(RegExp(r'\.?0+$'), '');
  return unit.isEmpty ? clean : '$clean $unit';
}

String formatLocalDateTime(String? isoStr) {
  if (isoStr == null || isoStr.isEmpty) return '-';
  final parsed = DateTime.tryParse(isoStr);
  if (parsed == null) return isoStr;
  final local = parsed.toLocal();
  return DateFormat('dd.MM.yyyy HH:mm').format(local);
}

String formatShortDate(String? isoStr) {
  if (isoStr == null || isoStr.isEmpty) return '-';
  final parsed = DateTime.tryParse(isoStr);
  if (parsed == null) return isoStr;
  return DateFormat('dd.MM').format(parsed.toLocal());
}

String formatPaymentMethod(String? method) {
  return switch ((method ?? '').trim().toLowerCase()) {
    'cash' => 'Naqd',
    'card' => 'Karta',
    'transfer' => "O'tkazma",
    '' => 'Naqd',
    final other => other,
  };
}

double? parseNumberInput(String raw) {
  final cleaned = raw
      .trim()
      .replaceAll('\u00A0', '')
      .replaceAll(' ', '')
      .replaceAll(',', '.');
  if (cleaned.isEmpty) return null;
  return double.tryParse(cleaned);
}

String joinMeta(List<String?> parts, {String sep = ' • '}) {
  return parts
      .map((e) => (e ?? '').trim())
      .where((e) => e.isNotEmpty)
      .join(sep);
}
