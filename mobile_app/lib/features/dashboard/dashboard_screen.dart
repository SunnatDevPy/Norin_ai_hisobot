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
    ('7', '7k'),
    ('30', '30k'),
    ('60', '60k'),
    ('90', '90k'),
  ];

  static const _pieColors = <Color>[
    NorinPalette.emeraldLight,
    NorinPalette.sky,
    NorinPalette.magenta,
    NorinPalette.amber,
    NorinPalette.profit,
    NorinPalette.indigo,
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
    final settingsAsync = ref.watch(settingsProvider);
    final tenantsAsync = auth.isSuperAdmin ? ref.watch(adminTenantsProvider) : null;
    final themeMode = ref.watch(themeModeProvider);
    final isDark = Theme.of(context).brightness == Brightness.dark;

    String activeTenantName = asStr(
      asMap(settingsAsync.valueOrNull?['tenant'])['name'],
      "Filial #${auth.selectedTenantId}",
    );
    final tenantsList = tenantsAsync?.valueOrNull ?? <Map<String, dynamic>>[];
    for (final t in tenantsList) {
      if (asInt(t['id']) == auth.selectedTenantId) {
        activeTenantName = asStr(t['tenant_name'] ?? t['name'], activeTenantName);
        break;
      }
    }

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        titleSpacing: 16,
        title: Row(
          children: [
            Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: NorinPalette.heroGradient,
                border: Border.all(
                  color: NorinPalette.magenta.withValues(alpha: 0.6),
                  width: 1.4,
                ),
                boxShadow: [
                  BoxShadow(
                    color: NorinPalette.emerald.withValues(alpha: 0.35),
                    blurRadius: 12,
                  ),
                ],
              ),
              child: const Icon(Icons.auto_awesome_rounded, size: 19, color: Colors.white),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "Salom, Norin AI!",
                    style: TextStyle(fontSize: 16.5, fontWeight: FontWeight.w800),
                  ),
                  Text(
                    activeTenantName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 11.5,
                      color: isDark ? NorinPalette.emeraldLight : NorinPalette.emeraldDark,
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
            _GlassCircleAction(
              tooltip: "Filialni almashtirish",
              icon: Icons.store_mall_directory_outlined,
              onPressed: () =>
                  _showTenantSwitcher(context, ref, tenantsList, auth.selectedTenantId),
            ),
          const SizedBox(width: 6),
          _GlassCircleAction(
            tooltip: "Mavzu (Kun/Tun)",
            icon: themeMode == ThemeMode.dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined,
            onPressed: () {
              final next = themeMode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark;
              ref.read(themeModeProvider.notifier).state = next;
            },
          ),
          const SizedBox(width: 6),
          _GlassCircleAction(
            tooltip: "Yangilash",
            icon: Icons.refresh_rounded,
            onPressed: () => invalidateOperationalData(ref),
          ),
          const SizedBox(width: 12),
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
          padding: const EdgeInsets.fromLTRB(16, 6, 16, 120),
          children: [
            // Date / Period pills + quick Excel button (reference top toolbar style)
            Row(
              children: [
                Expanded(
                  child: SizedBox(
                    height: 36,
                    child: ListView.separated(
                      scrollDirection: Axis.horizontal,
                      itemCount: _periods.length,
                      separatorBuilder: (_, _) => const SizedBox(width: 7),
                      itemBuilder: (ctx, i) {
                        final (key, label) = _periods[i];
                        final selected = key == period;
                        return InkWell(
                          onTap: () => ref.read(selectedPeriodProvider.notifier).state = key,
                          borderRadius: BorderRadius.circular(12),
                          child: AnimatedContainer(
                            duration: const Duration(milliseconds: 160),
                            padding: const EdgeInsets.symmetric(horizontal: 12),
                            alignment: Alignment.center,
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(12),
                              color: selected
                                  ? NorinPalette.emerald.withValues(alpha: isDark ? 0.24 : 0.14)
                                  : (isDark ? NorinPalette.darkCard : NorinPalette.lightCard),
                              border: Border.all(
                                color: selected
                                    ? NorinPalette.emeraldLight
                                    : (isDark
                                        ? NorinPalette.darkBorder
                                        : NorinPalette.lightBorder),
                              ),
                            ),
                            child: Text(
                              label,
                              style: TextStyle(
                                fontSize: 12,
                                fontWeight: selected ? FontWeight.w700 : FontWeight.w600,
                                color: selected
                                    ? (isDark ? Colors.white : NorinPalette.emeraldDark)
                                    : Theme.of(context).colorScheme.onSurfaceVariant,
                              ),
                            ),
                          ),
                        );
                      },
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                InkWell(
                  onTap: () {
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
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    height: 36,
                    padding: const EdgeInsets.symmetric(horizontal: 11),
                    decoration: BoxDecoration(
                      color: isDark ? NorinPalette.darkCard : NorinPalette.lightCard,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(
                        color: isDark ? NorinPalette.darkBorder : NorinPalette.lightBorder,
                      ),
                    ),
                    child: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.file_download_outlined, size: 16, color: NorinPalette.emeraldLight),
                        SizedBox(width: 5),
                        Text("Eksport", style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
                      ],
                    ),
                  ),
                ),
              ],
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

                final dailySeries = asMapList(chartsAsync.valueOrNull?['daily_series']);

                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (stale != null && stale.isNotEmpty) ...[
                      SpotlightHeroCard(
                        padding: const EdgeInsets.all(14),
                        glowColor: NorinPalette.amber,
                        accentColor: NorinPalette.danger,
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
                      const SizedBox(height: 12),
                    ],
                    // 1. "Earnings Distribution" style glowing capsule card
                    _EarningsDistributionCard(
                      revenue: revenue,
                      profit: profit,
                      cost: cost,
                      expenses: expenses,
                      returnsAmount: returnsAmount,
                      salesCount: salesCount,
                      totalKg: totalKg,
                      dateRange: periodInfo['start'] != null
                          ? "${asStr(periodInfo['start'])} — ${asStr(periodInfo['end'])}"
                          : null,
                    ),
                    const SizedBox(height: 12),
                    // 2. "Profit Margin" + purple spline sparkline card
                    _ProfitMarginSparkCard(
                      margin: margin,
                      profit: profit,
                      daily: dailySeries,
                    ),
                    const SizedBox(height: 12),
                    // 3. 2x2 Spotlight KPI Grid
                    GridView.count(
                      crossAxisCount: 2,
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      mainAxisSpacing: 10,
                      crossAxisSpacing: 10,
                      childAspectRatio: 1.52,
                      children: [
                        KpiCardTile(
                          title: cash.isNotEmpty ? "Kassa qoldig'i" : "Yig'ilgan pul",
                          value: formatCompactUzs(cash.isNotEmpty ? cashBalance : collectedTotal),
                          subtitle: formatUzs(cash.isNotEmpty ? cashBalance : collectedTotal),
                          icon: Icons.savings_outlined,
                          color: NorinPalette.emeraldLight,
                          highlight: true,
                          onTap: () => ref.read(shellTabIndexProvider.notifier).state = 2,
                        ),
                        KpiCardTile(
                          title: "Mijozlar qarzi",
                          value: formatCompactUzs(totalDebt),
                          subtitle: formatUzs(totalDebt),
                          icon: Icons.account_balance_outlined,
                          color: totalDebt > 0 ? NorinPalette.danger : NorinPalette.profit,
                          onTap: () => ref.read(shellTabIndexProvider.notifier).state = 1,
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
            const SizedBox(height: 16),
            // 4. "Cash Flow Trends" grouped glowing vertical bar chart + chartsAsync
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
                    _CashFlowBarTrendsCard(
                      daily: daily,
                      chartPeriod: chartPeriod,
                      periods: _chartPeriods,
                      onSelectPeriod: (p) => ref.read(chartPeriodProvider.notifier).state = p,
                    ),
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
            const SizedBox(height: 16),
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
                    trailing: selected
                        ? const Icon(Icons.check_circle_rounded, color: NorinPalette.emeraldLight)
                        : null,
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

class _GlassCircleAction extends StatelessWidget {
  const _GlassCircleAction({
    required this.tooltip,
    required this.icon,
    required this.onPressed,
  });

  final String tooltip;
  final IconData icon;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Tooltip(
      message: tooltip,
      child: InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(999),
        child: Container(
          width: 38,
          height: 38,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: isDark ? NorinPalette.darkCardElevated : NorinPalette.lightCard,
            border: Border.all(
              color: isDark ? NorinPalette.darkBorder : NorinPalette.lightBorder,
            ),
          ),
          child: Icon(icon, size: 19),
        ),
      ),
    );
  }
}

class _EarningsDistributionCard extends StatelessWidget {
  const _EarningsDistributionCard({
    required this.revenue,
    required this.profit,
    required this.cost,
    required this.expenses,
    required this.returnsAmount,
    required this.salesCount,
    required this.totalKg,
    this.dateRange,
  });

  final double revenue;
  final double profit;
  final double cost;
  final double expenses;
  final double returnsAmount;
  final int salesCount;
  final double totalKg;
  final String? dateRange;

  @override
  Widget build(BuildContext context) {
    final totalCostAndExp = math.max(0.0, cost + expenses);
    final posProfit = math.max(0.0, profit);
    final posRev = math.max(0.0, revenue);
    final sum = math.max(1.0, posRev + posProfit + totalCostAndExp);

    int flexOf(double v) => math.max(18, ((v / sum) * 100).round());

    return SpotlightHeroCard(
      padding: const EdgeInsets.all(18),
      glowColor: NorinPalette.emeraldLight,
      accentColor: NorinPalette.sky,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  "Daromad taqsimoti",
                  style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w800),
                ),
              ),
              Text(
                "$salesCount sotuv • ${formatKg(totalKg)}",
                style: TextStyle(
                  fontSize: 11.5,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          if (dateRange != null) ...[
            const SizedBox(height: 2),
            Text(
              dateRange!,
              style: TextStyle(
                fontSize: 11,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ],
          const SizedBox(height: 14),
          // 3 glowing capsule bars side by side (like "Earnings Distribution")
          SizedBox(
            height: 24,
            child: Row(
              children: [
                Expanded(
                  flex: flexOf(posRev),
                  child: _GlowingCapsuleBar(
                    gradient: NorinPalette.neonCyanGradient,
                    glowColor: NorinPalette.sky,
                  ),
                ),
                const SizedBox(width: 6),
                Expanded(
                  flex: flexOf(posProfit),
                  child: _GlowingCapsuleBar(
                    gradient: NorinPalette.neonMagentaGradient,
                    glowColor: NorinPalette.magenta,
                  ),
                ),
                const SizedBox(width: 6),
                Expanded(
                  flex: flexOf(totalCostAndExp),
                  child: Container(
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(8),
                      color: const Color(0xFF252336),
                      border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: _CapsuleMetricColumn(
                  amount: formatCompactUzs(revenue),
                  label: "Savdo tushum",
                  color: NorinPalette.sky,
                ),
              ),
              Expanded(
                child: _CapsuleMetricColumn(
                  amount: formatCompactUzs(profit),
                  label: "Sof foyda",
                  color: NorinPalette.magenta,
                ),
              ),
              Expanded(
                child: _CapsuleMetricColumn(
                  amount: formatCompactUzs(cost + returnsAmount),
                  label: returnsAmount > 0 ? "Tannarx/Vozv" : "Tannarx",
                  color: NorinPalette.darkMuted,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _GlowingCapsuleBar extends StatelessWidget {
  const _GlowingCapsuleBar({required this.gradient, required this.glowColor});
  final Gradient gradient;
  final Color glowColor;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        gradient: gradient,
        boxShadow: [
          BoxShadow(
            color: glowColor.withValues(alpha: 0.45),
            blurRadius: 12,
            offset: const Offset(0, 2),
          ),
        ],
      ),
    );
  }
}

class _CapsuleMetricColumn extends StatelessWidget {
  const _CapsuleMetricColumn({
    required this.amount,
    required this.label,
    required this.color,
  });

  final String amount;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerLeft,
          child: Text(
            amount,
            style: tNumStyle.copyWith(fontSize: 16, fontWeight: FontWeight.w800),
          ),
        ),
        const SizedBox(height: 4),
        Row(
          children: [
            Container(
              width: 3,
              height: 11,
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: 5),
            Flexible(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 11,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _ProfitMarginSparkCard extends StatelessWidget {
  const _ProfitMarginSparkCard({
    required this.margin,
    required this.profit,
    required this.daily,
  });

  final double margin;
  final double profit;
  final List<Map<String, dynamic>> daily;

  @override
  Widget build(BuildContext context) {
    final spots = <FlSpot>[];
    if (daily.isNotEmpty) {
      final slice = daily.length > 10 ? daily.sublist(daily.length - 10) : daily;
      for (int i = 0; i < slice.length; i++) {
        spots.add(FlSpot(i.toDouble(), asDouble(slice[i]['profit'])));
      }
    }
    final isPos = profit >= 0;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Row(
          children: [
            Expanded(
              flex: 5,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    "Foyda Marjasi",
                    style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: (isPos ? NorinPalette.profit : NorinPalette.danger)
                          .withValues(alpha: 0.16),
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(
                      "${isPos ? '+' : ''}${formatCompactUzs(profit)} ${isPos ? '▲' : '▼'}",
                      style: tNumStyle.copyWith(
                        fontSize: 11,
                        fontWeight: FontWeight.w800,
                        color: isPos ? NorinPalette.profit : NorinPalette.danger,
                      ),
                    ),
                  ),
                  const SizedBox(height: 6),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.baseline,
                    textBaseline: TextBaseline.alphabetic,
                    children: [
                      Text(
                        margin.toStringAsFixed(1),
                        style: tNumStyle.copyWith(
                          fontSize: 32,
                          fontWeight: FontWeight.w900,
                          letterSpacing: -0.8,
                        ),
                      ),
                      const SizedBox(width: 4),
                      Text(
                        "%",
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              flex: 6,
              child: SizedBox(
                height: 82,
                child: spots.length < 2
                    ? Center(
                        child: Text(
                          "Dinamika kutilmoqda",
                          style: TextStyle(
                            fontSize: 11,
                            color: Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                        ),
                      )
                    : LineChart(
                        LineChartData(
                          gridData: const FlGridData(show: false),
                          titlesData: const FlTitlesData(show: false),
                          borderData: FlBorderData(show: false),
                          lineTouchData: const LineTouchData(enabled: false),
                          lineBarsData: [
                            LineChartBarData(
                              spots: spots,
                              isCurved: true,
                              preventCurveOverShooting: true,
                              color: NorinPalette.emeraldLight,
                              barWidth: 2.5,
                              dotData: FlDotData(
                                show: true,
                                getDotPainter: (spot, percent, bar, index) => FlDotCirclePainter(
                                  radius: 3.2,
                                  color: NorinPalette.magenta,
                                  strokeWidth: 1.5,
                                  strokeColor: const Color(0xFF13121B),
                                ),
                              ),
                              belowBarData: BarAreaData(
                                show: true,
                                gradient: LinearGradient(
                                  begin: Alignment.topCenter,
                                  end: Alignment.bottomCenter,
                                  colors: [
                                    NorinPalette.emerald.withValues(alpha: 0.24),
                                    Colors.transparent,
                                  ],
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
              ),
            ),
          ],
        ),
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
                  const SizedBox(height: 6),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(999),
                    child: LinearProgressIndicator(
                      value: ratio,
                      minHeight: 7,
                      backgroundColor: NorinPalette.emerald.withValues(alpha: 0.14),
                      color: NorinPalette.emeraldLight,
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

class _CashFlowBarTrendsCard extends StatelessWidget {
  const _CashFlowBarTrendsCard({
    required this.daily,
    required this.chartPeriod,
    required this.periods,
    required this.onSelectPeriod,
  });

  final List<Map<String, dynamic>> daily;
  final String chartPeriod;
  final List<(String, String)> periods;
  final ValueChanged<String> onSelectPeriod;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final view = daily.length > 8 ? daily.sublist(daily.length - 8) : daily;
    double maxY = 1;
    for (final d in view) {
      maxY = math.max(maxY, math.max(asDouble(d['revenue']), math.max(0, asDouble(d['profit']))));
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 16, 16, 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        "Pul oqimi dinamikasi",
                        style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
                      ),
                      SizedBox(height: 2),
                      Text(
                        "Kunlik savdo tushumi va sof foyda",
                        style: TextStyle(fontSize: 11.5, color: NorinPalette.darkMuted),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.all(3),
                  decoration: BoxDecoration(
                    color: isDark ? NorinPalette.darkBg : NorinPalette.lightBg,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: isDark ? NorinPalette.darkBorder : NorinPalette.lightBorder,
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: periods.map((p) {
                      final active = p.$1 == chartPeriod;
                      return InkWell(
                        onTap: () => onSelectPeriod(p.$1),
                        borderRadius: BorderRadius.circular(8),
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(8),
                            color: active
                                ? NorinPalette.emerald.withValues(alpha: 0.25)
                                : Colors.transparent,
                          ),
                          child: Text(
                            p.$2,
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: active ? FontWeight.w800 : FontWeight.w600,
                              color: active ? NorinPalette.emeraldLight : NorinPalette.darkMuted,
                            ),
                          ),
                        ),
                      );
                    }).toList(),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 18),
            if (view.isEmpty)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 28),
                child: Center(child: Text("Grafik uchun hali sotuvlar yo'q")),
              )
            else
              SizedBox(
                height: 210,
                child: BarChart(
                  BarChartData(
                    maxY: maxY * 1.18,
                    minY: 0,
                    alignment: BarChartAlignment.spaceAround,
                    gridData: FlGridData(
                      show: true,
                      drawVerticalLine: false,
                      getDrawingHorizontalLine: (_) => FlLine(
                        color: Theme.of(context).dividerColor.withValues(alpha: 0.4),
                        strokeWidth: 1,
                        dashArray: [4, 4],
                      ),
                    ),
                    borderData: FlBorderData(show: false),
                    barTouchData: BarTouchData(
                      touchTooltipData: BarTouchTooltipData(
                        getTooltipColor: (_) => const Color(0xFF1D1A2B),
                        tooltipRoundedRadius: 10,
                        getTooltipItem: (group, groupIndex, rod, rodIndex) {
                          final idx = group.x.toInt();
                          final date = idx >= 0 && idx < view.length
                              ? formatShortDate(asStr(view[idx]['date']))
                              : '';
                          final kind = rodIndex == 0 ? 'Savdo' : 'Foyda';
                          return BarTooltipItem(
                            '$date • $kind\n${formatCompactUzs(rod.toY)}',
                            const TextStyle(
                              color: Colors.white,
                              fontSize: 11.5,
                              fontWeight: FontWeight.w700,
                            ),
                          );
                        },
                      ),
                    ),
                    titlesData: FlTitlesData(
                      topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                      rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                      leftTitles: AxisTitles(
                        sideTitles: SideTitles(
                          showTitles: true,
                          reservedSize: 48,
                          getTitlesWidget: (v, _) => Padding(
                            padding: const EdgeInsets.only(right: 6),
                            child: Text(
                              formatCompactUzs(v),
                              style: const TextStyle(fontSize: 10, color: NorinPalette.darkMuted),
                            ),
                          ),
                        ),
                      ),
                      bottomTitles: AxisTitles(
                        sideTitles: SideTitles(
                          showTitles: true,
                          reservedSize: 24,
                          getTitlesWidget: (v, _) {
                            final idx = v.toInt();
                            if (idx < 0 || idx >= view.length) return const SizedBox.shrink();
                            return Padding(
                              padding: const EdgeInsets.only(top: 6),
                              child: Text(
                                formatShortDate(asStr(view[idx]['date'])),
                                style: const TextStyle(fontSize: 10, color: NorinPalette.darkMuted),
                              ),
                            );
                          },
                        ),
                      ),
                    ),
                    barGroups: [
                      for (int i = 0; i < view.length; i++)
                        BarChartGroupData(
                          x: i,
                          barsSpace: 4,
                          barRods: [
                            BarChartRodData(
                              toY: math.max(0, asDouble(view[i]['revenue'])),
                              width: view.length <= 5 ? 14 : 10,
                              borderRadius: const BorderRadius.vertical(top: Radius.circular(5)),
                              gradient: const LinearGradient(
                                begin: Alignment.bottomCenter,
                                end: Alignment.topCenter,
                                colors: [Color(0xFF6D28D9), NorinPalette.magenta],
                              ),
                            ),
                            BarChartRodData(
                              toY: math.max(0, asDouble(view[i]['profit'])),
                              width: view.length <= 5 ? 14 : 10,
                              borderRadius: const BorderRadius.vertical(top: Radius.circular(5)),
                              gradient: const LinearGradient(
                                begin: Alignment.bottomCenter,
                                end: Alignment.topCenter,
                                colors: [Color(0xFF0284C7), Color(0xFF67E8F9)],
                              ),
                            ),
                          ],
                        ),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 10),
            const Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _LegendDot(color: NorinPalette.magenta, label: "Savdo tushum"),
                SizedBox(width: 18),
                _LegendDot(color: NorinPalette.sky, label: "Sof foyda"),
              ],
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
                    width: 132,
                    height: 132,
                    child: PieChart(
                      PieChartData(
                        sectionsSpace: 2,
                        centerSpaceRadius: 34,
                        sections: [
                          for (int i = 0; i < expenses.length; i++)
                            PieChartSectionData(
                              value: asDouble(expenses[i]['amount']),
                              color: colors[i % colors.length],
                              radius: 26,
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
            ? NorinPalette.magenta.withValues(alpha: 0.22)
            : NorinPalette.emerald.withValues(alpha: 0.14),
        child: Text(
          '$rank',
          style: TextStyle(
            fontWeight: FontWeight.w800,
            color: rank == 1 ? NorinPalette.magenta : NorinPalette.emeraldLight,
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
              style: const TextStyle(
                color: NorinPalette.danger,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
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
        Container(
          width: 9,
          height: 9,
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
            boxShadow: [BoxShadow(color: color.withValues(alpha: 0.6), blurRadius: 6)],
          ),
        ),
        const SizedBox(width: 6),
        Text(label, style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600)),
      ],
    );
  }
}

class _DashboardSkeleton extends StatelessWidget {
  const _DashboardSkeleton();

  @override
  Widget build(BuildContext context) {
    return SpotlightHeroCard(
      padding: const EdgeInsets.all(42),
      child: const Center(child: CircularProgressIndicator()),
    );
  }
}
