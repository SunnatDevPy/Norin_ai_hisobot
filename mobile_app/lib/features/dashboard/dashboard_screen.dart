import 'dart:math' as math;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/metric_cards.dart';
import '../../core/widgets/norin_widgets.dart';
import '../cash/cash_screen.dart';
import '../clients/client_detail_screen.dart';
import '../shell/main_shell.dart';

class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  static const _periods = <(String, String)>[
    ('today', 'Bugun'),
    ('7', '7 kun'),
    ('cur', 'Shu oy'),
    ('prev', "O'tgan oy"),
    ('30', '30 kun'),
  ];

  static const _chartPeriods = <(String, String)>[
    ('7', '7 kun'),
    ('30', '30 kun'),
    ('60', '60 kun'),
    ('90', '90 kun'),
  ];

  static const _pieColors = <Color>[
    NorinPalette.emerald,
    NorinPalette.sky,
    NorinPalette.amber,
    NorinPalette.indigo,
    Color(0xFFEC4899),
    Color(0xFF8B5CF6),
    NorinPalette.danger,
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    final period = ref.watch(selectedPeriodProvider);
    final chartPeriod = ref.watch(chartPeriodProvider);
    final summaryAsync = ref.watch(dashboardSummaryProvider);
    final chartsAsync = ref.watch(dashboardChartsProvider);
    final todayAsync = ref.watch(todayProvider);
    final tenantsAsync = auth.isSuperAdmin ? ref.watch(adminTenantsProvider) : null;
    final themeMode = ref.watch(themeModeProvider);

    String activeTenantName = "Filial #${auth.selectedTenantId}";
    final tenantsList = tenantsAsync?.valueOrNull ?? <Map<String, dynamic>>[];
    for (final t in tenantsList) {
      if (asInt(t['id']) == auth.selectedTenantId) {
        activeTenantName = asStr(t['tenant_name'] ?? t['name'], activeTenantName);
        break;
      }
    }

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(7),
              decoration: BoxDecoration(
                gradient: NorinPalette.heroGradient,
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Icon(Icons.analytics_rounded, size: 18, color: Colors.white),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "Norin AI",
                    style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
                  ),
                  Text(
                    activeTenantName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 11.5,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
        actions: [
          if (auth.isSuperAdmin)
            IconButton(
              tooltip: "Filialni almashtirish",
              icon: const Icon(Icons.store_mall_directory_outlined),
              onPressed: () => _showTenantSwitcher(context, ref, tenantsList, auth.selectedTenantId),
            ),
          IconButton(
            tooltip: "Mavzu (Kun/Tun)",
            icon: Icon(
              themeMode == ThemeMode.dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined,
            ),
            onPressed: () {
              final next = themeMode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark;
              ref.read(themeModeProvider.notifier).state = next;
            },
          ),
          IconButton(
            tooltip: "Yangilash",
            icon: const Icon(Icons.refresh_rounded),
            onPressed: () => invalidateOperationalData(ref),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          invalidateOperationalData(ref);
          await Future.wait([
            ref.read(dashboardSummaryProvider.future),
            ref.read(dashboardChartsProvider.future),
          ]);
        },
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 100),
          children: [
            SizedBox(
              height: 40,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: _periods.length,
                separatorBuilder: (_, _) => const SizedBox(width: 8),
                itemBuilder: (ctx, i) {
                  final (key, label) = _periods[i];
                  final selected = key == period;
                  return ChoiceChip(
                    label: Text(label),
                    selected: selected,
                    onSelected: (_) => ref.read(selectedPeriodProvider.notifier).state = key,
                  );
                },
              ),
            ),
            const SizedBox(height: 14),
            summaryAsync.when(
              loading: () => const _DashboardSkeleton(),
              error: (e, _) => AsyncErrorCard(
                error: e,
                onRetry: () => ref.invalidate(dashboardSummaryProvider),
              ),
              data: (summary) {
                final kpis = asMap(summary['kpis']);
                final periodInfo = asMap(summary['period']);
                final collected = asMap(summary['collected']);
                final cash = asMap(summary['cash']);
                final weightMap = asMap(summary['weight_by_product']);
                final stale = summary['stale_open_session'] == null
                    ? null
                    : asMap(summary['stale_open_session']);

                final profit = asDouble(kpis['profit']);
                final margin = asDouble(kpis['margin_pct']);
                final revenue = asDouble(kpis['revenue']);
                final cost = asDouble(kpis['cost']);
                final totalKg = asDouble(kpis['total_kg']);
                final salesCount = asInt(kpis['sales_count']);
                final returnsAmount = asDouble(kpis['returns_amount']);
                final expenses = asDouble(kpis['expenses']);
                final totalDebt = asDouble(summary['total_clients_debt']);
                final kassaDebt = asDouble(summary['kassa_debt_outstanding']);
                final cashBalance = cash.isNotEmpty
                    ? asDouble(cash['expected_balance'])
                    : (asDouble(collected['cash']) - expenses);
                final collectedTotal = asDouble(collected['cash']) +
                    asDouble(collected['card']) +
                    asDouble(collected['transfer']);

                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (stale != null && stale.isNotEmpty) ...[
                      Card(
                        color: NorinPalette.amber.withValues(alpha: 0.14),
                        child: Padding(
                          padding: const EdgeInsets.all(14),
                          child: Row(
                            children: [
                              const Icon(Icons.warning_amber_rounded, color: NorinPalette.amber),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Text(
                                  "Ochiq eski smena bor: ${asStr(stale['report_date'])}",
                                  style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 13),
                                ),
                              ),
                              FilledButton.tonal(
                                onPressed: () => openCloseDayDialog(
                                  context,
                                  ref,
                                  sessionId: asInt(stale['id']),
                                  reportDate: asStr(stale['report_date']),
                                ),
                                child: const Text("Yopish"),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],
                    _ProfitHeroCard(
                      profit: profit,
                      margin: margin,
                      revenue: revenue,
                      cost: cost,
                      returnsAmount: returnsAmount,
                      totalKg: totalKg,
                      salesCount: salesCount,
                      dateRange: periodInfo['start'] != null
                          ? "${asStr(periodInfo['start'])} — ${asStr(periodInfo['end'])}"
                          : null,
                    ),
                    const SizedBox(height: 12),
                    GridView.count(
                      crossAxisCount: 2,
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      mainAxisSpacing: 10,
                      crossAxisSpacing: 10,
                      childAspectRatio: 1.52,
                      children: [
                        KpiCardTile(
                          title: "Mijozlar qarzi",
                          value: formatCompactUzs(totalDebt),
                          subtitle: formatUzs(totalDebt),
                          icon: Icons.account_balance_outlined,
                          color: totalDebt > 0 ? NorinPalette.danger : NorinPalette.profit,
                          onTap: () => ref.read(shellTabIndexProvider.notifier).state = 1,
                        ),
                        KpiCardTile(
                          title: cash.isNotEmpty ? "Kassa qoldig'i" : "Yig'ilgan pul",
                          value: formatCompactUzs(cash.isNotEmpty ? cashBalance : collectedTotal),
                          subtitle: formatUzs(cash.isNotEmpty ? cashBalance : collectedTotal),
                          icon: Icons.savings_outlined,
                          color: NorinPalette.emerald,
                          onTap: () => ref.read(shellTabIndexProvider.notifier).state = 2,
                        ),
                        KpiCardTile(
                          title: "Yig'im (Naqd/Karta)",
                          value: formatCompactUzs(collectedTotal),
                          subtitle:
                              "Naqd ${formatCompactUzs(asDouble(collected['cash']))} • Karta ${formatCompactUzs(asDouble(collected['card']))}",
                          icon: Icons.payments_outlined,
                          color: NorinPalette.sky,
                        ),
                        KpiCardTile(
                          title: "Xarajatlar",
                          value: formatCompactUzs(expenses),
                          subtitle: kassaDebt > 0
                              ? "Kassa qarz: ${formatCompactUzs(kassaDebt)}"
                              : formatUzs(expenses),
                          icon: Icons.receipt_long_outlined,
                          color: NorinPalette.amber,
                          onTap: () => ref.read(shellTabIndexProvider.notifier).state = 2,
                        ),
                      ],
                    ),
                    if (weightMap.isNotEmpty) ...[
                      const SizedBox(height: 16),
                      const SectionHeader(title: "Mahsulotlar kesimida (kg)"),
                      const SizedBox(height: 8),
                      _ProductWeightBreakdown(weightMap: weightMap),
                    ],
                  ],
                );
              },
            ),
            const SizedBox(height: 18),
            SectionHeader(
              title: "Dinamika & Tahlil",
              trailing: SizedBox(
                height: 32,
                child: SegmentedButton<String>(
                  showSelectedIcon: false,
                  style: ButtonStyle(
                    visualDensity: VisualDensity.compact,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    textStyle: WidgetStatePropertyAll(
                      Theme.of(context).textTheme.labelSmall?.copyWith(fontWeight: FontWeight.w700),
                    ),
                  ),
                  segments: _chartPeriods
                      .map((p) => ButtonSegment<String>(value: p.$1, label: Text(p.$2)))
                      .toList(),
                  selected: {chartPeriod},
                  onSelectionChanged: (s) {
                    if (s.isNotEmpty) {
                      ref.read(chartPeriodProvider.notifier).state = s.first;
                    }
                  },
                ),
              ),
            ),
            const SizedBox(height: 10),
            chartsAsync.when(
              loading: () => const Card(
                child: Padding(
                  padding: EdgeInsets.all(36),
                  child: Center(child: CircularProgressIndicator()),
                ),
              ),
              error: (e, _) => AsyncErrorCard(
                error: e,
                onRetry: () => ref.invalidate(dashboardChartsProvider),
              ),
              data: (charts) {
                final daily = asMapList(charts['daily_series']);
                final expList = asMapList(charts['expense_breakdown']);
                final topClients = asMapList(charts['top_clients']);
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _RevenueProfitLineChart(daily: daily),
                    const SizedBox(height: 12),
                    _ExpensePieCard(expenses: expList, colors: _pieColors),
                    const SizedBox(height: 16),
                    const SectionHeader(title: "Top Mijozlar"),
                    const SizedBox(height: 8),
                    if (topClients.isEmpty)
                      const EmptyStateCard(
                        icon: Icons.leaderboard_outlined,
                        title: "Bu davrda sotuvlar topilmadi",
                      )
                    else
                      Card(
                        child: Column(
                          children: [
                            for (int i = 0; i < topClients.length; i++) ...[
                              if (i > 0) const Divider(),
                              _TopClientRow(
                                rank: i + 1,
                                client: topClients[i],
                                onTap: () => _openTopClient(context, ref, topClients[i]),
                              ),
                            ],
                          ],
                        ),
                      ),
                  ],
                );
              },
            ),
            const SizedBox(height: 18),
            const SectionHeader(title: "Excel Hisobotlar"),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: FilledButton.tonalIcon(
                    onPressed: () {
                      final p = period == 'today' ? '30' : period;
                      showExcelActionPicker(
                        context,
                        ref.read(apiClientProvider),
                        title: "Davriy hisobot Excel",
                        path: '/export/period',
                        query: {'period': p},
                        filename: 'Norin_Davriy_$p.xlsx',
                      );
                    },
                    icon: const Icon(Icons.table_chart_outlined),
                    label: const Text("Davriy"),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: FilledButton.tonalIcon(
                    onPressed: () {
                      final sessId = asInt(asMap(todayAsync.valueOrNull?['session'])['id']);
                      if (sessId <= 0) {
                        showSnack(context, "Bugungi smena topilmadi", error: true);
                        return;
                      }
                      showExcelActionPicker(
                        context,
                        ref.read(apiClientProvider),
                        title: "Kunlik hisobot Excel",
                        path: '/export/daily/$sessId',
                        filename: 'Norin_Kunlik_$sessId.xlsx',
                      );
                    },
                    icon: const Icon(Icons.today_outlined),
                    label: const Text("Bugungi"),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: FilledButton.tonalIcon(
                    onPressed: () => showExcelActionPicker(
                      context,
                      ref.read(apiClientProvider),
                      title: "Yopilgan kunlar tarixi",
                      path: '/export/history',
                      filename: 'Norin_Kunlik_Tarix.xlsx',
                    ),
                    icon: const Icon(Icons.history_rounded),
                    label: const Text("Tarix"),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _openTopClient(
    BuildContext context,
    WidgetRef ref,
    Map<String, dynamic> top,
  ) async {
    int cid = asInt(top['id']);
    final name = asStr(top['name']);
    if (cid <= 0) {
      final list = ref.read(clientsProvider).valueOrNull ?? const [];
      for (final c in list) {
        if (asStr(c['name']).toLowerCase() == name.toLowerCase()) {
          cid = asInt(c['id']);
          break;
        }
      }
    }
    if (cid > 0 && context.mounted) {
      await Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => ClientDetailScreen(clientId: cid, initialName: name),
        ),
      );
      invalidateOperationalData(ref);
    } else {
      ref.read(shellTabIndexProvider.notifier).state = 1;
    }
  }

  Future<void> _showTenantSwitcher(
    BuildContext context,
    WidgetRef ref,
    List<Map<String, dynamic>> tenants,
    int currentId,
  ) async {
    if (tenants.isEmpty) {
      ref.invalidate(adminTenantsProvider);
    }
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => Consumer(
        builder: (ctx, sheetRef, _) {
          final asyncTenants = sheetRef.watch(adminTenantsProvider);
          return SafeArea(
            child: asyncTenants.when(
              loading: () => const SizedBox(
                height: 180,
                child: Center(child: CircularProgressIndicator()),
              ),
              error: (e, _) => AsyncErrorCard(
                error: e,
                onRetry: () => sheetRef.invalidate(adminTenantsProvider),
              ),
              data: (list) => ListView.separated(
                shrinkWrap: true,
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 20),
                itemCount: list.length + 1,
                separatorBuilder: (_, _) => const SizedBox(height: 6),
                itemBuilder: (ctx, i) {
                  if (i == 0) {
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Text(
                        "Filialni tanlang (Super Admin)",
                        style: Theme.of(ctx).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
                      ),
                    );
                  }
                  final t = list[i - 1];
                  final tid = asInt(t['id']);
                  final name = asStr(t['tenant_name'] ?? t['name'], 'Filial #$tid');
                  final selected = tid == currentId;
                  return ListTile(
                    selected: selected,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                    leading: CircleAvatar(
                      backgroundColor: selected ? NorinPalette.emerald : null,
                      foregroundColor: selected ? Colors.white : null,
                      child: Text('#$tid'),
                    ),
                    title: Text(name, style: const TextStyle(fontWeight: FontWeight.w700)),
                    subtitle: Text(
                      "${asStr(t['plan_name'], 'Standard')} • ${asStr(t['status'])}",
                    ),
                    trailing: selected ? const Icon(Icons.check_circle_rounded, color: NorinPalette.emerald) : null,
                    onTap: () async {
                      Navigator.pop(ctx);
                      await ref.read(authProvider.notifier).selectTenant(tid);
                      invalidateOperationalData(ref);
                      if (context.mounted) {
                        showSnack(context, "Faol filial: $name");
                      }
                    },
                  );
                },
              ),
            ),
          );
        },
      ),
    );
  }
}

class _ProfitHeroCard extends StatelessWidget {
  const _ProfitHeroCard({
    required this.profit,
    required this.margin,
    required this.revenue,
    required this.cost,
    required this.returnsAmount,
    required this.totalKg,
    required this.salesCount,
    this.dateRange,
  });

  final double profit;
  final double margin;
  final double revenue;
  final double cost;
  final double returnsAmount;
  final double totalKg;
  final int salesCount;
  final String? dateRange;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: NorinPalette.heroGradient,
        borderRadius: BorderRadius.circular(22),
        boxShadow: [
          BoxShadow(
            color: NorinPalette.emerald.withValues(alpha: 0.24),
            blurRadius: 20,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text(
                "SOF FOYDA",
                style: TextStyle(
                  color: Colors.white70,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.8,
                ),
              ),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  "${margin.toStringAsFixed(1)}% marja",
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          FittedBox(
            fit: BoxFit.scaleDown,
            alignment: Alignment.centerLeft,
            child: Text(
              formatUzs(profit),
              style: tNumStyle.copyWith(
                color: Colors.white,
                fontSize: 30,
                fontWeight: FontWeight.w900,
                letterSpacing: -0.5,
              ),
            ),
          ),
          if (dateRange != null) ...[
            const SizedBox(height: 4),
            Text(
              "$dateRange • $salesCount ta sotuv • ${formatKg(totalKg)}",
              style: const TextStyle(color: Colors.white70, fontSize: 12),
            ),
          ],
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.black.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Row(
              children: [
                _HeroMiniStat(label: "Savdo", value: formatCompactUzs(revenue)),
                _HeroMiniStat(label: "Tannarx", value: formatCompactUzs(cost)),
                _HeroMiniStat(label: "Vozvrat", value: formatCompactUzs(returnsAmount)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _HeroMiniStat extends StatelessWidget {
  const _HeroMiniStat({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: const TextStyle(color: Colors.white70, fontSize: 11)),
          const SizedBox(height: 2),
          Text(
            value,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: tNumStyle.copyWith(
              color: Colors.white,
              fontSize: 14,
              fontWeight: FontWeight.w800,
            ),
          ),
        ],
      ),
    );
  }
}

class _ProductWeightBreakdown extends StatelessWidget {
  const _ProductWeightBreakdown({required this.weightMap});
  final Map<String, dynamic> weightMap;

  @override
  Widget build(BuildContext context) {
    final entries = weightMap.entries.toList()
      ..sort((a, b) => asDouble(b.value).compareTo(asDouble(a.value)));
    final total = entries.fold<double>(0, (s, e) => s + asDouble(e.value));

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          children: entries.map((e) {
            final kg = asDouble(e.value);
            final ratio = total > 0 ? (kg / total).clamp(0.0, 1.0) : 0.0;
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(e.key, style: const TextStyle(fontWeight: FontWeight.w600)),
                      ),
                      Text(
                        "${formatKg(kg)} (${(ratio * 100).toStringAsFixed(0)}%)",
                        style: tNumStyle.copyWith(fontWeight: FontWeight.w700, fontSize: 13),
                      ),
                    ],
                  ),
                  const SizedBox(height: 5),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(999),
                    child: LinearProgressIndicator(
                      value: ratio,
                      minHeight: 7,
                      backgroundColor: NorinPalette.emerald.withValues(alpha: 0.12),
                      color: NorinPalette.emerald,
                    ),
                  ),
                ],
              ),
            );
          }).toList(),
        ),
      ),
    );
  }
}

class _RevenueProfitLineChart extends StatelessWidget {
  const _RevenueProfitLineChart({required this.daily});
  final List<Map<String, dynamic>> daily;

  @override
  Widget build(BuildContext context) {
    if (daily.isEmpty) {
      return const EmptyStateCard(
        icon: Icons.show_chart_rounded,
        title: "Grafik uchun yetarli ma'lumot yo'q",
        subtitle: "Sotuvlar qo'shilgach kunlik tushum va foyda grafigi paydo bo'ladi.",
      );
    }

    final revSpots = <FlSpot>[];
    final profSpots = <FlSpot>[];
    double maxY = 1;
    double minY = 0;

    for (int i = 0; i < daily.length; i++) {
      final rev = asDouble(daily[i]['revenue']);
      final prof = asDouble(daily[i]['profit']);
      revSpots.add(FlSpot(i.toDouble(), rev));
      profSpots.add(FlSpot(i.toDouble(), prof));
      maxY = math.max(maxY, math.max(rev, prof));
      minY = math.min(minY, math.min(rev, prof));
    }

    final step = math.max(1, (daily.length / 4).ceil());

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 16, 18, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  "Tushum va Sof foyda",
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                ),
                const Spacer(),
                _LegendDot(color: NorinPalette.sky, label: "Savdo"),
                const SizedBox(width: 10),
                _LegendDot(color: NorinPalette.profit, label: "Foyda"),
              ],
            ),
            const SizedBox(height: 16),
            SizedBox(
              height: 210,
              child: LineChart(
                LineChartData(
                  minY: minY < 0 ? minY * 1.15 : 0,
                  maxY: maxY * 1.15,
                  gridData: FlGridData(
                    show: true,
                    drawVerticalLine: false,
                    getDrawingHorizontalLine: (_) => FlLine(
                      color: Theme.of(context).dividerColor.withValues(alpha: 0.4),
                      strokeWidth: 1,
                    ),
                  ),
                  borderData: FlBorderData(show: false),
                  lineTouchData: LineTouchData(
                    touchTooltipData: LineTouchTooltipData(
                      getTooltipColor: (_) => const Color(0xFF0F172A),
                      getTooltipItems: (spots) => spots.map((s) {
                        final idx = s.x.toInt();
                        final dateStr = idx >= 0 && idx < daily.length
                            ? formatShortDate(asStr(daily[idx]['date']))
                            : '';
                        final kind = s.barIndex == 0 ? 'Savdo' : 'Foyda';
                        return LineTooltipItem(
                          '$dateStr $kind\n${formatCompactUzs(s.y)}',
                          const TextStyle(
                            color: Colors.white,
                            fontSize: 11.5,
                            fontWeight: FontWeight.w700,
                          ),
                        );
                      }).toList(),
                    ),
                  ),
                  titlesData: FlTitlesData(
                    topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                    leftTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        reservedSize: 54,
                        getTitlesWidget: (v, _) => Padding(
                          padding: const EdgeInsets.only(right: 6),
                          child: Text(
                            formatCompactUzs(v),
                            style: const TextStyle(fontSize: 10),
                          ),
                        ),
                      ),
                    ),
                    bottomTitles: AxisTitles(
                      sideTitles: SideTitles(
                        showTitles: true,
                        reservedSize: 26,
                        interval: step.toDouble(),
                        getTitlesWidget: (v, _) {
                          final idx = v.round();
                          if (idx < 0 || idx >= daily.length) return const SizedBox.shrink();
                          return Padding(
                            padding: const EdgeInsets.only(top: 6),
                            child: Text(
                              formatShortDate(asStr(daily[idx]['date'])),
                              style: const TextStyle(fontSize: 10),
                            ),
                          );
                        },
                      ),
                    ),
                  ),
                  lineBarsData: [
                    LineChartBarData(
                      spots: revSpots,
                      isCurved: true,
                      preventCurveOverShooting: true,
                      color: NorinPalette.sky,
                      barWidth: 2.8,
                      dotData: FlDotData(show: daily.length <= 14),
                      belowBarData: BarAreaData(
                        show: true,
                        color: NorinPalette.sky.withValues(alpha: 0.12),
                      ),
                    ),
                    LineChartBarData(
                      spots: profSpots,
                      isCurved: true,
                      preventCurveOverShooting: true,
                      color: NorinPalette.profit,
                      barWidth: 2.8,
                      dotData: FlDotData(show: daily.length <= 14),
                      belowBarData: BarAreaData(
                        show: true,
                        color: NorinPalette.profit.withValues(alpha: 0.14),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ExpensePieCard extends StatelessWidget {
  const _ExpensePieCard({required this.expenses, required this.colors});
  final List<Map<String, dynamic>> expenses;
  final List<Color> colors;

  @override
  Widget build(BuildContext context) {
    final total = expenses.fold<double>(0, (s, e) => s + asDouble(e['amount']));
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              "Xarajatlar tarkibi",
              style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 12),
            if (expenses.isEmpty || total <= 0)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 14),
                child: Center(child: Text("Bu davrda xarajatlar kiritilmagan")),
              )
            else
              Row(
                children: [
                  SizedBox(
                    width: 136,
                    height: 136,
                    child: PieChart(
                      PieChartData(
                        sectionsSpace: 2,
                        centerSpaceRadius: 34,
                        sections: [
                          for (int i = 0; i < expenses.length; i++)
                            PieChartSectionData(
                              value: asDouble(expenses[i]['amount']),
                              color: colors[i % colors.length],
                              radius: 28,
                              showTitle: false,
                            ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        for (int i = 0; i < expenses.length; i++)
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 3.5),
                            child: Row(
                              children: [
                                Container(
                                  width: 10,
                                  height: 10,
                                  decoration: BoxDecoration(
                                    color: colors[i % colors.length],
                                    shape: BoxShape.circle,
                                  ),
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    asStr(expenses[i]['category'], 'Boshqa'),
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
                                  ),
                                ),
                                Text(
                                  formatCompactUzs(asDouble(expenses[i]['amount'])),
                                  style: tNumStyle.copyWith(fontSize: 12.5, fontWeight: FontWeight.w700),
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

class _TopClientRow extends StatelessWidget {
  const _TopClientRow({
    required this.rank,
    required this.client,
    required this.onTap,
  });

  final int rank;
  final Map<String, dynamic> client;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final name = asStr(client['name'], 'Mijoz');
    final rev = asDouble(client['revenue']);
    final kg = asDouble(client['kg']);
    final debt = asDouble(client['current_debt']);
    return ListTile(
      onTap: onTap,
      leading: CircleAvatar(
        backgroundColor: rank == 1
            ? NorinPalette.amber.withValues(alpha: 0.2)
            : NorinPalette.emerald.withValues(alpha: 0.12),
        child: Text(
          '$rank',
          style: TextStyle(
            fontWeight: FontWeight.w800,
            color: rank == 1 ? NorinPalette.amber : NorinPalette.emerald,
          ),
        ),
      ),
      title: Text(name, style: const TextStyle(fontWeight: FontWeight.w700)),
      subtitle: Text("${formatKg(kg)} • ${asInt(client['sales_count'])} ta sotuv"),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(
            formatCompactUzs(rev),
            style: tNumStyle.copyWith(fontWeight: FontWeight.w800, fontSize: 14),
          ),
          if (debt > 0)
            Text(
              "Qarz: ${formatCompactUzs(debt)}",
              style: const TextStyle(color: NorinPalette.danger, fontSize: 11, fontWeight: FontWeight.w600),
            ),
        ],
      ),
    );
  }
}

class _LegendDot extends StatelessWidget {
  const _LegendDot({required this.color, required this.label});
  final Color color;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 9, height: 9, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        const SizedBox(width: 5),
        Text(label, style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600)),
      ],
    );
  }
}

class _DashboardSkeleton extends StatelessWidget {
  const _DashboardSkeleton();

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Container(
          height: 170,
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.45),
            borderRadius: BorderRadius.circular(22),
          ),
          child: const Center(child: CircularProgressIndicator()),
        ),
      ],
    );
  }
}
