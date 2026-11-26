import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/metric_cards.dart';
import '../../core/widgets/norin_widgets.dart';
import '../sales/sale_sheets.dart';

const kExpenseCategories = <String>[
  "Xomashyo",
  "Tovar / Yuk",
  "Qadoqlash",
  "Ish haqi",
  "Transport",
  "Ijara / Komunal",
  "Masalliq",
  "Boshqa",
];

Future<void> openCloseDayDialog(
  BuildContext context,
  WidgetRef ref, {
  int? sessionId,
  String? reportDate,
  double? expectedCash,
}) async {
  await ActionGuard.run('dlg:close_day', () async {
    final countedCtrl = TextEditingController(
      text: expectedCash != null ? expectedCash.round().toString() : '',
    );
    bool notifyReport = true;
    bool decided = false;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) {
          final counted = parseNumberInput(countedCtrl.text) ?? 0;
          final diff = expectedCash != null ? (counted - expectedCash) : null;
          return AlertDialog(
            title: Text(
              reportDate != null && reportDate.isNotEmpty
                  ? "Kunni yopish ($reportDate)"
                  : "Bugungi kunni yopish",
            ),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (expectedCash != null) ...[
                    Text(
                      "Hisob bo'yicha naqd kassa:",
                      style: TextStyle(fontSize: 12, color: Theme.of(ctx).colorScheme.onSurfaceVariant),
                    ),
                    Text(
                      formatUzs(expectedCash),
                      style: tNumStyle.copyWith(fontSize: 18, fontWeight: FontWeight.w800),
                    ),
                    const SizedBox(height: 12),
                  ],
                  TextField(
                    controller: countedCtrl,
                    keyboardType: TextInputType.number,
                    onChanged: (_) => setDlg(() {}),
                    decoration: const InputDecoration(
                      labelText: "Sanalgan naqd pul (so'm) *",
                      prefixIcon: Icon(Icons.payments_outlined),
                    ),
                  ),
                  if (diff != null) ...[
                    const SizedBox(height: 10),
                    Container(
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: (diff == 0 ? NorinPalette.profit : NorinPalette.amber)
                            .withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Row(
                        children: [
                          const Text("Sverka farqi:", style: TextStyle(fontWeight: FontWeight.w600)),
                          const Spacer(),
                          Text(
                            "${diff > 0 ? '+' : ''}${formatUzs(diff)}",
                            style: tNumStyle.copyWith(
                              fontWeight: FontWeight.w800,
                              color: diff < 0 ? NorinPalette.danger : NorinPalette.profit,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                  const SizedBox(height: 8),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text("Hisobot guruhiga yuborish"),
                    value: notifyReport,
                    onChanged: (v) => setDlg(() => notifyReport = v),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () {
                  if (decided) return;
                  decided = true;
                  Navigator.pop(ctx, false);
                },
                child: const Text("Bekor"),
              ),
              FilledButton(
                onPressed: () {
                  if (decided) return;
                  decided = true;
                  Navigator.pop(ctx, true);
                },
                child: const Text("Kunni yopish"),
              ),
            ],
          );
        },
      ),
    );
    if (ok != true) return;
    final counted = parseNumberInput(countedCtrl.text);
    if (counted == null || counted < 0) {
      if (context.mounted) showSnack(context, "Sanalgan summani to'g'ri kiriting", error: true);
      return;
    }
    try {
      await ref.read(apiClientProvider).post(
        '/cash/close-day',
        data: {
          'counted_cash': counted,
          if (sessionId != null && sessionId > 0) 'session_id': sessionId,
          'notify_report_group': notifyReport,
        },
      );
      invalidateOperationalData(ref);
      if (context.mounted) showSnack(context, "Smena muvaffaqiyatli yopildi");
    } catch (e) {
      if (context.mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  });
}

Future<void> openQuickCashTxDialog(
  BuildContext context,
  WidgetRef ref,
  String sourceType,
) async {
  await ActionGuard.run('dlg:cash_tx:$sourceType', () async {
    final (String title, bool needCategory) = switch (sourceType) {
      'expense' => ("Xarajat qo'shish", true),
      'main_in' => ("Kassaga kirim", false),
      'kassa_debt' => ("Kassaga qarz olish", false),
      _ => ("Kassa qarzini qaytarish", false),
    };
    final amountCtrl = TextEditingController();
    final noteCtrl = TextEditingController();
    String category = kExpenseCategories.first;
    bool decided = false;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          title: Text(title),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  controller: amountCtrl,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: "Summa (so'm) *"),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: [
                    for (final preset in const [50000, 100000, 250000, 500000])
                      ActionChip(
                        visualDensity: VisualDensity.compact,
                        label: Text("+${formatCompactUzs(preset)}"),
                        onPressed: () {
                          final cur = parseNumberInput(amountCtrl.text) ?? 0;
                          amountCtrl.text = (cur + preset).round().toString();
                          setDlg(() {});
                        },
                      ),
                  ],
                ),
                if (needCategory) ...[
                  const SizedBox(height: 12),
                  const Text("Kategoriya:", style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 6),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: kExpenseCategories
                        .map(
                          (cat) => ChoiceChip(
                            label: Text(cat),
                            selected: category == cat,
                            onSelected: (_) => setDlg(() => category = cat),
                          ),
                        )
                        .toList(),
                  ),
                ],
                const SizedBox(height: 12),
                TextField(
                  controller: noteCtrl,
                  decoration: const InputDecoration(labelText: "Izoh (ixtiyoriy)"),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () {
                if (decided) return;
                decided = true;
                Navigator.pop(ctx, false);
              },
              child: const Text("Bekor"),
            ),
            FilledButton(
              onPressed: () {
                if (decided) return;
                decided = true;
                Navigator.pop(ctx, true);
              },
              child: const Text("Saqlash"),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final amount = parseNumberInput(amountCtrl.text);
    if (amount == null || amount <= 0) {
      if (context.mounted) showSnack(context, "Summa 0 dan katta bo'lishi kerak", error: true);
      return;
    }
    try {
      await ref.read(apiClientProvider).post(
        '/cash/transactions',
        data: {
          'amount': amount,
          'source_type': sourceType,
          if (needCategory) 'category': category,
          'note': noteCtrl.text.trim(),
        },
      );
      invalidateOperationalData(ref);
      if (context.mounted) showSnack(context, "Kassa amaliyoti saqlandi");
    } catch (e) {
      if (context.mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  });
}

Future<void> openQuickPaymentDialog(
  BuildContext context,
  WidgetRef ref, {
  int? initialClientId,
  VoidCallback? onSuccess,
}) async {
  await ActionGuard.run('dlg:quick_pay', () async {
    List<Map<String, dynamic>> clients =
        ref.read(clientsProvider).valueOrNull ?? const <Map<String, dynamic>>[];
    if (clients.isEmpty) {
      try {
        clients = await ref.read(clientsProvider.future);
      } catch (e) {
        if (context.mounted) showSnack(context, ApiClient.extractError(e), error: true);
        return;
      }
    }
    if (!context.mounted) return;
    if (clients.isEmpty) {
      showSnack(context, "Avval mijoz qo'shing", error: true);
      return;
    }

    Map<String, dynamic> findClient(int? id) {
      for (final c in clients) {
        if (asInt(c['id']) == id) return c;
      }
      return clients.first;
    }

    int selectedId = initialClientId ?? asInt(clients.first['id']);
    if (!clients.any((c) => asInt(c['id']) == selectedId)) {
      selectedId = asInt(clients.first['id']);
    }

    final amountCtrl = TextEditingController();
    final noteCtrl = TextEditingController();
    String method = 'cash';
    bool postGroup = findClient(selectedId)['group_chat_id'] != null;
    bool decided = false;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) {
          final cli = findClient(selectedId);
          final debt = asDouble(cli['current_debt']);
          final hasGroup = cli['group_chat_id'] != null;
          return AlertDialog(
            title: const Text("Mijozdan pul olish"),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  DropdownButtonFormField<int>(
                    key: ValueKey('pay_cli_$selectedId'),
                    initialValue: selectedId,
                    isExpanded: true,
                    decoration: const InputDecoration(
                      labelText: "Mijoz",
                      prefixIcon: Icon(Icons.person_outline),
                    ),
                    items: clients.map((c) {
                      final d = asDouble(c['current_debt']);
                      return DropdownMenuItem<int>(
                        value: asInt(c['id']),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(
                                asStr(c['name']),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            if (d != 0)
                              Text(
                                formatCompactUzs(d),
                                style: tNumStyle.copyWith(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  color: d > 0 ? NorinPalette.danger : NorinPalette.profit,
                                ),
                              ),
                          ],
                        ),
                      );
                    }).toList(),
                    onChanged: (v) {
                      if (v == null) return;
                      setDlg(() {
                        selectedId = v;
                        postGroup = findClient(v)['group_chat_id'] != null;
                      });
                    },
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: amountCtrl,
                    keyboardType: TextInputType.number,
                    decoration: InputDecoration(
                      labelText: "Summa (so'm) *",
                      helperText: debt > 0 ? "Joriy qarz: ${formatUzs(debt)}" : null,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 6,
                    runSpacing: 4,
                    children: [
                      if (debt > 0) ...[
                        ActionChip(
                          visualDensity: VisualDensity.compact,
                          label: const Text("To'liq qarz"),
                          onPressed: () {
                            amountCtrl.text = debt.round().toString();
                            setDlg(() {});
                          },
                        ),
                        ActionChip(
                          visualDensity: VisualDensity.compact,
                          label: const Text("50%"),
                          onPressed: () {
                            amountCtrl.text = (debt / 2).round().toString();
                            setDlg(() {});
                          },
                        ),
                      ],
                      ActionChip(
                        visualDensity: VisualDensity.compact,
                        label: const Text("+100k"),
                        onPressed: () {
                          final cur = parseNumberInput(amountCtrl.text) ?? 0;
                          amountCtrl.text = (cur + 100000).round().toString();
                          setDlg(() {});
                        },
                      ),
                      ActionChip(
                        visualDensity: VisualDensity.compact,
                        label: const Text("+500k"),
                        onPressed: () {
                          final cur = parseNumberInput(amountCtrl.text) ?? 0;
                          amountCtrl.text = (cur + 500000).round().toString();
                          setDlg(() {});
                        },
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  SegmentedButton<String>(
                    showSelectedIcon: false,
                    segments: const [
                      ButtonSegment(value: 'cash', label: Text("Naqd")),
                      ButtonSegment(value: 'card', label: Text("Karta")),
                      ButtonSegment(value: 'transfer', label: Text("O'tkazma")),
                    ],
                    selected: {method},
                    onSelectionChanged: (s) => setDlg(() => method = s.first),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: noteCtrl,
                    decoration: const InputDecoration(labelText: "Izoh (ixtiyoriy)"),
                  ),
                  if (hasGroup)
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text("Guruhga yuborish"),
                      value: postGroup,
                      onChanged: (v) => setDlg(() => postGroup = v),
                    ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () {
                  if (decided) return;
                  decided = true;
                  Navigator.pop(ctx, false);
                },
                child: const Text("Bekor"),
              ),
              FilledButton(
                onPressed: () {
                  if (decided) return;
                  decided = true;
                  Navigator.pop(ctx, true);
                },
                child: const Text("Saqlash"),
              ),
            ],
          );
        },
      ),
    );
    if (ok != true) return;
    final amount = parseNumberInput(amountCtrl.text);
    if (amount == null || amount <= 0) {
      if (context.mounted) showSnack(context, "Summa 0 dan katta bo'lishi kerak", error: true);
      return;
    }
    try {
      final res = asMap(
        await ref.read(apiClientProvider).post(
          '/payments',
          data: {
            'client_id': selectedId,
            'amount': amount,
            'payment_method': method,
            'note': noteCtrl.text.trim(),
            'post_to_group': postGroup,
          },
        ),
      );
      invalidateOperationalData(ref);
      onSuccess?.call();
      if (context.mounted) {
        showSnack(
          context,
          res['group_posted'] == true ? "To'lov saqlandi va guruhga yuborildi" : "To'lov saqlandi",
        );
      }
    } catch (e) {
      if (context.mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  });
}

Future<void> openEditPaymentDialog(
  BuildContext context,
  WidgetRef ref,
  Map<String, dynamic> payment, {
  VoidCallback? onSuccess,
}) async {
  await ActionGuard.run('dlg:edit_pay:${asInt(payment['id'])}', () async {
    final amountCtrl = TextEditingController(text: asDouble(payment['amount']).round().toString());
    final noteCtrl = TextEditingController(text: asStr(payment['note']));
    String method = asStr(payment['payment_method'], 'cash');
    if (!const ['cash', 'card', 'transfer'].contains(method)) method = 'cash';
    bool decided = false;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          title: const Text("To'lovni tahrirlash"),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: amountCtrl,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: "Summa (so'm) *"),
                ),
                const SizedBox(height: 12),
                SegmentedButton<String>(
                  showSelectedIcon: false,
                  segments: const [
                    ButtonSegment(value: 'cash', label: Text("Naqd")),
                    ButtonSegment(value: 'card', label: Text("Karta")),
                    ButtonSegment(value: 'transfer', label: Text("O'tkazma")),
                  ],
                  selected: {method},
                  onSelectionChanged: (s) => setDlg(() => method = s.first),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: noteCtrl,
                  decoration: const InputDecoration(labelText: "Izoh"),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () {
                if (decided) return;
                decided = true;
                Navigator.pop(ctx, false);
              },
              child: const Text("Bekor"),
            ),
            FilledButton(
              onPressed: () {
                if (decided) return;
                decided = true;
                Navigator.pop(ctx, true);
              },
              child: const Text("Saqlash"),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final amount = parseNumberInput(amountCtrl.text);
    if (amount == null || amount <= 0) {
      if (context.mounted) showSnack(context, "Summa 0 dan katta bo'lishi kerak", error: true);
      return;
    }
    try {
      await ref.read(apiClientProvider).patch(
        '/payments/${asInt(payment['id'])}',
        data: {
          'amount': amount,
          'payment_method': method,
          'note': noteCtrl.text.trim(),
        },
      );
      invalidateOperationalData(ref);
      onSuccess?.call();
      if (context.mounted) showSnack(context, "To'lov yangilandi");
    } catch (e) {
      if (context.mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  });
}

Future<void> openEditCashTxDialog(
  BuildContext context,
  WidgetRef ref,
  Map<String, dynamic> tx,
) async {
  await ActionGuard.run('dlg:edit_tx:${asInt(tx['id'])}', () async {
    final amountCtrl = TextEditingController(text: asDouble(tx['amount']).round().toString());
    final noteCtrl = TextEditingController(text: asStr(tx['note']));
    bool decided = false;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Kassa yozuvini tahrirlash"),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: amountCtrl,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: "Summa (so'm) *"),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: noteCtrl,
              decoration: const InputDecoration(labelText: "Izoh"),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              if (decided) return;
              decided = true;
              Navigator.pop(ctx, false);
            },
            child: const Text("Bekor"),
          ),
          FilledButton(
            onPressed: () {
              if (decided) return;
              decided = true;
              Navigator.pop(ctx, true);
            },
            child: const Text("Saqlash"),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final amount = parseNumberInput(amountCtrl.text);
    if (amount == null || amount <= 0) {
      if (context.mounted) showSnack(context, "Summa 0 dan katta bo'lishi kerak", error: true);
      return;
    }
    try {
      await ref.read(apiClientProvider).patch(
        '/cash/transactions/${asInt(tx['id'])}',
        data: {'amount': amount, 'note': noteCtrl.text.trim()},
      );
      invalidateOperationalData(ref);
      if (context.mounted) showSnack(context, "Yozuv yangilandi");
    } catch (e) {
      if (context.mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  });
}

class CashScreen extends ConsumerStatefulWidget {
  const CashScreen({super.key});

  @override
  ConsumerState<CashScreen> createState() => _CashScreenState();
}

class _CashScreenState extends ConsumerState<CashScreen> {
  int _segment = 0; // 0: Sotuvlar, 1: To'lovlar, 2: Vozvrat, 3: Xarajat/Kassa

  Future<void> _showHistorySheet() async {
    await ActionGuard.run('sheet:history', () async {
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        showDragHandle: true,
        builder: (ctx) => SafeArea(top: false, child: _SessionHistorySheet(parentRef: ref)),
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final todayAsync = ref.watch(todayProvider);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: const Text("Kassa", style: TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          IconButton(
            tooltip: "Yopilgan kunlar tarixi",
            icon: const Icon(Icons.history_rounded),
            onPressed: _showHistorySheet,
          ),
          SpinningRefreshButton(
            onRefresh: () async {
              ref.invalidate(todayProvider);
              await ref.read(todayProvider.future).catchError((_) => <String, dynamic>{});
            },
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(todayProvider);
          await ref.read(todayProvider.future);
        },
        child: todayAsync.when(
          loading: () => const _CashSkeleton(),
          error: (e, _) => AsyncErrorCard(
            error: e,
            onRetry: () => ref.invalidate(todayProvider),
          ),
          data: (today) {
            final session = asMap(today['session']);
            final cash = asMap(today['cash']);
            final sales = asMapList(today['sales']);
            final payments = asMapList(today['payments']);
            final returns = asMapList(today['returns']);
            final txs = asMapList(today['cash_transactions']);

            final expected = asDouble(cash['expected_balance']);
            final opening = asDouble(cash['opening_balance']);
            final cashIn = asDouble(cash['client_cash_in']);
            final mainIn = asDouble(cash['main_cash_in']);
            final totalExp = asDouble(cash['total_expenses']);
            final kassaDebtOut = asDouble(cash['kassa_debt_outstanding']);
            final isClosed = asStr(session['status']) == 'closed';

            return ListView(
              padding: EdgeInsets.fromLTRB(16, 8, 16, dockBottomClearance(context)),
              children: [
                SpotlightHeroCard(
                  padding: const EdgeInsets.all(18),
                  borderRadius: 20,
                  glowColor: NorinPalette.sky,
                  accentColor: NorinPalette.emeraldLight,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text(
                            "KASSA (${asStr(session['report_date'])})",
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.7,
                            ),
                          ),
                          const Spacer(),
                          Container(
                            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                            decoration: BoxDecoration(
                              color: (isClosed ? NorinPalette.amber : NorinPalette.emerald)
                                  .withValues(alpha: 0.16),
                              borderRadius: BorderRadius.circular(999),
                            ),
                            child: Text(
                              isClosed ? "Yopilgan" : "Ochiq smena",
                              style: const TextStyle(
                                fontSize: 11.5,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),
                      AnimatedCountText(
                        key: ValueKey('cash_${ref.watch(refreshEpochProvider)}'),
                        value: expected,
                        formatter: formatUzs,
                        style: tNumStyle.copyWith(
                          fontSize: 28,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        "Boshi: ${formatCompactUzs(opening)}  •  Naqd tushum: ${formatCompactUzs(cashIn)}  •  Kirim: ${formatCompactUzs(mainIn)}  •  Xarajat: ${formatCompactUzs(totalExp)}",
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                          fontSize: 12,
                        ),
                      ),
                      if (kassaDebtOut > 0) ...[
                        const SizedBox(height: 4),
                        Text(
                          "Kassa qarzi qoldig'i: ${formatUzs(kassaDebtOut)}",
                          style: const TextStyle(
                            color: NorinPalette.amber,
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                Column(
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: PressableScale(
                            scaleFactor: 0.96,
                            child: FilledButton.tonalIcon(
                              onPressed: () => openQuickPaymentDialog(context, ref),
                              icon: const Icon(Icons.payments_outlined, color: NorinPalette.profit, size: 19),
                              label: const FittedBox(fit: BoxFit.scaleDown, child: Text("Pul oldim")),
                            ),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: PressableScale(
                            scaleFactor: 0.96,
                            child: FilledButton.tonalIcon(
                              onPressed: () => openQuickCashTxDialog(context, ref, 'expense'),
                              icon: const Icon(Icons.remove_circle_outline, color: NorinPalette.danger, size: 19),
                              label: const FittedBox(fit: BoxFit.scaleDown, child: Text("Xarajat")),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(
                          child: PressableScale(
                            scaleFactor: 0.96,
                            child: OutlinedButton.icon(
                              onPressed: () => openQuickCashTxDialog(context, ref, 'main_in'),
                              icon: const Icon(Icons.add_circle_outline, color: NorinPalette.profit, size: 19),
                              label: const FittedBox(fit: BoxFit.scaleDown, child: Text("Kirim")),
                            ),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: PressableScale(
                            scaleFactor: 0.96,
                            child: OutlinedButton.icon(
                              onPressed: () => openQuickCashTxDialog(context, ref, 'kassa_debt'),
                              icon: const Icon(Icons.account_balance_outlined, size: 19),
                              label: const FittedBox(fit: BoxFit.scaleDown, child: Text("Kassa qarz")),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(
                          child: PressableScale(
                            scaleFactor: 0.96,
                            child: OutlinedButton.icon(
                              onPressed: () => openQuickCashTxDialog(context, ref, 'kassa_repay'),
                              icon: const Icon(Icons.keyboard_return_rounded, size: 19),
                              label: const FittedBox(fit: BoxFit.scaleDown, child: Text("Qaytarish")),
                            ),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: !isClosed
                              ? PressableScale(
                                  scaleFactor: 0.96,
                                  child: FilledButton.icon(
                                    onPressed: () => openCloseDayDialog(
                                      context,
                                      ref,
                                      sessionId: asInt(session['id']),
                                      reportDate: asStr(session['report_date']),
                                      expectedCash: expected,
                                    ),
                                    icon: const Icon(Icons.lock_clock_outlined, size: 19),
                                    label: const FittedBox(
                                      fit: BoxFit.scaleDown,
                                      child: Text("Kunni yopish"),
                                    ),
                                  ),
                                )
                              : PressableScale(
                                  scaleFactor: 0.96,
                                  child: OutlinedButton.icon(
                                    onPressed: () async {
                                      try {
                                        await ref
                                            .read(apiClientProvider)
                                            .post('/cash/reopen/${asInt(session['id'])}');
                                        invalidateOperationalData(ref);
                                        if (context.mounted) showSnack(context, "Smena qayta ochildi");
                                      } catch (e) {
                                        if (context.mounted) {
                                          showSnack(context, ApiClient.extractError(e), error: true);
                                        }
                                      }
                                    },
                                    icon: const Icon(Icons.lock_open_rounded, size: 19),
                                    label: const FittedBox(
                                      fit: BoxFit.scaleDown,
                                      child: Text("Qayta ochish"),
                                    ),
                                  ),
                                ),
                        ),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                SizedBox(
                  height: 40,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    children: [
                      ChoiceChip(
                        label: Text("Sotuvlar (${sales.length})"),
                        selected: _segment == 0,
                        onSelected: (_) => setState(() => _segment = 0),
                      ),
                      const SizedBox(width: 10),
                      ChoiceChip(
                        label: Text("To'lovlar (${payments.length})"),
                        selected: _segment == 1,
                        onSelected: (_) => setState(() => _segment = 1),
                      ),
                      const SizedBox(width: 10),
                      ChoiceChip(
                        label: Text("Vozvrat (${returns.length})"),
                        selected: _segment == 2,
                        onSelected: (_) => setState(() => _segment = 2),
                      ),
                      const SizedBox(width: 10),
                      ChoiceChip(
                        label: Text("Xarajat/Kassa (${txs.length})"),
                        selected: _segment == 3,
                        onSelected: (_) => setState(() => _segment = 3),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 200),
                  child: KeyedSubtree(
                    key: ValueKey(_segment),
                    child: _segment == 0
                        ? _buildSalesList(sales)
                        : _segment == 1
                            ? _buildPaymentsList(payments)
                            : _segment == 2
                                ? _buildReturnsList(returns)
                                : _buildTxList(txs),
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _buildSalesList(List<Map<String, dynamic>> sales) {
    if (sales.isEmpty) {
      return const EmptyStateCard(icon: Icons.shopping_bag_outlined, title: "Bugun sotuvlar yo'q");
    }
    return Column(
      children: sales.map((s) {
        final isConf = asStr(s['status']) == 'confirmed';
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Card(
            child: ListTile(
              onTap: () => openSaleReviewSheet(context, ref, s),
              leading: CircleAvatar(
                backgroundColor:
                    (isConf ? NorinPalette.profit : NorinPalette.amber).withValues(alpha: 0.14),
                child: Icon(
                  isConf ? Icons.check_rounded : Icons.hourglass_top_rounded,
                  color: isConf ? NorinPalette.profit : NorinPalette.amber,
                ),
              ),
              title: Text(
                asStr(s['client_name'], "Noma'lum mijoz (#${asInt(s['id'])})"),
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              subtitle: Text(
                "${formatKg(asDouble(s['total_weight_kg']))} • ${formatLocalDateTime(asStr(s['created_at']))}",
              ),
              trailing: Text(
                formatUzs(asDouble(s['total_amount'])),
                style: tNumStyle.copyWith(fontWeight: FontWeight.w800),
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildPaymentsList(List<Map<String, dynamic>> payments) {
    if (payments.isEmpty) {
      return const EmptyStateCard(icon: Icons.payments_outlined, title: "Bugun to'lovlar yo'q");
    }
    return Column(
      children: payments.map((p) {
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Card(
            child: ListTile(
              onTap: () => openEditPaymentDialog(context, ref, p),
              leading: const CircleAvatar(
                backgroundColor: Color(0x1A059669),
                child: Icon(Icons.payments_outlined, color: NorinPalette.profit),
              ),
              title: Text(
                asStr(p['client_name'], "Mijoz #${asInt(p['client_id'])}"),
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              subtitle: Text(
                joinMeta([
                  formatPaymentMethod(asStr(p['payment_method'])),
                  asStr(p['note']),
                ]),
              ),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    formatUzs(asDouble(p['amount'])),
                    style: tNumStyle.copyWith(color: NorinPalette.profit, fontWeight: FontWeight.w800),
                  ),
                  IconButton(
                    icon: const Icon(Icons.delete_outline, color: NorinPalette.danger, size: 20),
                    onPressed: () async {
                      final yes = await showConfirmDialog(
                        context,
                        title: "To'lovni o'chirish",
                        message: "To'lov o'chirilsinmi?",
                        destructive: true,
                      );
                      if (!yes) return;
                      try {
                        await ref.read(apiClientProvider).delete('/payments/${asInt(p['id'])}');
                        invalidateOperationalData(ref);
                        if (mounted) showSnack(context, "To'lov o'chirildi");
                      } catch (e) {
                        if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
                      }
                    },
                  ),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildReturnsList(List<Map<String, dynamic>> returns) {
    if (returns.isEmpty) {
      return const EmptyStateCard(
        icon: Icons.assignment_return_outlined,
        title: "Bugun vozvratlar yo'q",
      );
    }
    return Column(
      children: returns.map((r) {
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Card(
            child: ListTile(
              leading: const CircleAvatar(
                backgroundColor: Color(0x1AF59E0B),
                child: Icon(Icons.assignment_return_outlined, color: NorinPalette.amber),
              ),
              title: Text(
                "${asStr(r['client_name'], 'Mijoz')} — ${asStr(r['product_name'])}",
                style: const TextStyle(fontWeight: FontWeight.w700),
              ),
              subtitle: Text(
                joinMeta([formatKg(asDouble(r['weight_kg'])), asStr(r['reason'])]),
              ),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    formatCompactUzs(asDouble(r['total_amount'])),
                    style: tNumStyle.copyWith(fontWeight: FontWeight.w800),
                  ),
                  IconButton(
                    icon: const Icon(Icons.delete_outline, color: NorinPalette.danger, size: 20),
                    onPressed: () async {
                      final yes = await showConfirmDialog(
                        context,
                        title: "Vozvratni o'chirish",
                        message: "Vozvrat o'chirilsinmi?",
                        destructive: true,
                      );
                      if (!yes) return;
                      try {
                        await ref.read(apiClientProvider).delete('/returns/${asInt(r['id'])}');
                        invalidateOperationalData(ref);
                        if (mounted) showSnack(context, "Vozvrat o'chirildi");
                      } catch (e) {
                        if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
                      }
                    },
                  ),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildTxList(List<Map<String, dynamic>> txs) {
    if (txs.isEmpty) {
      return const EmptyStateCard(
        icon: Icons.receipt_long_outlined,
        title: "Bugun kassa harakatlari yo'q",
      );
    }
    return Column(
      children: txs.map((tx) {
        final st = asStr(tx['source_type']);
        final isIn = st == 'main_in' || st == 'kassa_debt';
        final label = switch (st) {
          'expense' => asStr(tx['category'], 'Xarajat'),
          'main_in' => 'Kassaga kirim',
          'kassa_debt' => 'Kassa qarz',
          _ => 'Qarz qaytarish',
        };
        return Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Card(
            child: ListTile(
              onTap: () => openEditCashTxDialog(context, ref, tx),
              leading: CircleAvatar(
                backgroundColor:
                    (isIn ? NorinPalette.profit : NorinPalette.danger).withValues(alpha: 0.14),
                child: Icon(
                  isIn ? Icons.arrow_downward_rounded : Icons.arrow_upward_rounded,
                  color: isIn ? NorinPalette.profit : NorinPalette.danger,
                ),
              ),
              title: Text(label, style: const TextStyle(fontWeight: FontWeight.w700)),
              subtitle: Text(
                joinMeta([asStr(tx['note']), formatLocalDateTime(asStr(tx['created_at']))]),
              ),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    "${isIn ? '+' : '-'}${formatCompactUzs(asDouble(tx['amount']))}",
                    style: tNumStyle.copyWith(
                      fontWeight: FontWeight.w800,
                      color: isIn ? NorinPalette.profit : NorinPalette.danger,
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.delete_outline, size: 20, color: NorinPalette.danger),
                    onPressed: () async {
                      final yes = await showConfirmDialog(
                        context,
                        title: "Yozuvni o'chirish",
                        message: "Kassa yozuvi o'chirilsinmi?",
                        destructive: true,
                      );
                      if (!yes) return;
                      try {
                        await ref.read(apiClientProvider).delete('/cash/transactions/${asInt(tx['id'])}');
                        invalidateOperationalData(ref);
                        if (mounted) showSnack(context, "Yozuv o'chirildi");
                      } catch (e) {
                        if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
                      }
                    },
                  ),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }
}

class _CashSkeleton extends StatelessWidget {
  const _CashSkeleton();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: EdgeInsets.fromLTRB(16, 8, 16, dockBottomClearance(context)),
      children: const [
        CosmicShimmerBox(height: 126, borderRadius: 20),
        SizedBox(height: 12),
        CosmicShimmerBox(height: 44, borderRadius: 14),
        SizedBox(height: 16),
        CosmicShimmerBox(height: 68, borderRadius: 18),
        SizedBox(height: 8),
        CosmicShimmerBox(height: 68, borderRadius: 18),
        SizedBox(height: 8),
        CosmicShimmerBox(height: 68, borderRadius: 18),
      ],
    );
  }
}

class _SessionHistorySheet extends StatefulWidget {
  const _SessionHistorySheet({required this.parentRef});
  final WidgetRef parentRef;

  @override
  State<_SessionHistorySheet> createState() => _SessionHistorySheetState();
}

class _SessionHistorySheetState extends State<_SessionHistorySheet> {
  late Future<List<Map<String, dynamic>>> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    _future = widget.parentRef
        .read(apiClientProvider)
        .get('/history/sessions')
        .then((d) => asMapList(d));
  }

  void _openDayDetail(int sid, String reportDate) {
    ActionGuard.run('sheet:day_detail:$sid', () async {
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        showDragHandle: true,
        builder: (ctx) => SafeArea(
          top: false,
          child: _SessionDetailSheet(
            api: widget.parentRef.read(apiClientProvider),
            sessionId: sid,
            reportDate: reportDate,
          ),
        ),
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.72,
      maxChildSize: 0.92,
      builder: (ctx, sc) => FutureBuilder<List<Map<String, dynamic>>>(
        future: _future,
        builder: (ctx, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return AsyncErrorCard(
              error: snap.error!,
              onRetry: () => setState(_load),
            );
          }
          final sessions = snap.data ?? const [];
          return ListView.separated(
            controller: sc,
            padding: EdgeInsets.fromLTRB(20, 4, 20, screenBottomClearance(ctx, extra: 40)),
            itemCount: sessions.length + 1,
            separatorBuilder: (_, _) => const SizedBox(height: 8),
            itemBuilder: (ctx, i) {
              if (i == 0) {
                return Row(
                  children: [
                    const Text(
                      "Smenalar Tarixi",
                      style: TextStyle(fontSize: 19, fontWeight: FontWeight.w800),
                    ),
                    const Spacer(),
                    TextButton.icon(
                      onPressed: () => showExcelActionPicker(
                        context,
                        widget.parentRef.read(apiClientProvider),
                        title: "Tarix Excel",
                        path: '/export/history',
                        filename: 'SotuvAI_Kunlik_Tarix.xlsx',
                      ),
                      icon: const Icon(Icons.table_chart_outlined),
                      label: const Text("Excel"),
                    ),
                  ],
                );
              }
              final s = sessions[i - 1];
              final sid = asInt(s['id']);
              final rDate = asStr(s['report_date']);
              final closed = asStr(s['status']) == 'closed';
              return Card(
                child: ListTile(
                  onTap: () => _openDayDetail(sid, rDate),
                  title: Text(
                    rDate,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  subtitle: Text(
                    closed
                        ? "Sanalgan: ${formatUzs(asDouble(s['counted_cash']))} • Farq: ${formatUzs(asDouble(s['difference']))}"
                        : "Ochiq smena",
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        tooltip: "Kunlik Excel",
                        icon: const Icon(Icons.download_rounded),
                        onPressed: () => showExcelActionPicker(
                          context,
                          widget.parentRef.read(apiClientProvider),
                          title: "Kunlik Excel ($rDate)",
                          path: '/export/daily/$sid',
                          filename: 'SotuvAI_$rDate.xlsx',
                        ),
                      ),
                      if (closed)
                        IconButton(
                          tooltip: "Qayta ochish",
                          icon: const Icon(Icons.lock_open_rounded),
                          onPressed: () async {
                            try {
                              await widget.parentRef
                                  .read(apiClientProvider)
                                  .post('/cash/reopen/$sid');
                              invalidateOperationalData(widget.parentRef);
                              setState(_load);
                              if (context.mounted) showSnack(context, "Smena qayta ochildi");
                            } catch (e) {
                              if (context.mounted) {
                                showSnack(context, ApiClient.extractError(e), error: true);
                              }
                            }
                          },
                        ),
                    ],
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}

class _SessionDetailSheet extends StatefulWidget {
  const _SessionDetailSheet({
    required this.api,
    required this.sessionId,
    required this.reportDate,
  });

  final ApiClient api;
  final int sessionId;
  final String reportDate;

  @override
  State<_SessionDetailSheet> createState() => _SessionDetailSheetState();
}

class _SessionDetailSheetState extends State<_SessionDetailSheet> {
  late Future<Map<String, dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    _future = widget.api
        .get('/history/sessions/${widget.sessionId}')
        .then((d) => asMap(d));
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.65,
      maxChildSize: 0.9,
      builder: (ctx, sc) => FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (ctx, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return const Center(child: CircularProgressIndicator());
          }
          if (snap.hasError) {
            return AsyncErrorCard(error: snap.error!, onRetry: () => setState(_load));
          }
          final data = snap.data ?? const <String, dynamic>{};
          final kpis = asMap(data['kpis']);
          final cash = asMap(data['cash']);
          final sales = asMapList(data['sales']);
          final payments = asMapList(data['payments']);

          return ListView(
            controller: sc,
            padding: EdgeInsets.fromLTRB(20, 4, 20, screenBottomClearance(ctx, extra: 40)),
            children: [
              Row(
                children: [
                  Text(
                    "Kunlik hisobot — ${widget.reportDate}",
                    style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
                  ),
                  const Spacer(),
                  IconButton(
                    tooltip: "Excel yuklash",
                    icon: const Icon(Icons.download_rounded),
                    onPressed: () => showExcelActionPicker(
                      context,
                      widget.api,
                      title: "Kunlik Excel (${widget.reportDate})",
                      path: '/export/daily/${widget.sessionId}',
                      filename: 'SotuvAI_${widget.reportDate}.xlsx',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              SpotlightHeroCard(
                padding: const EdgeInsets.all(16),
                borderRadius: 18,
                glowColor: NorinPalette.emeraldLight,
                accentColor: NorinPalette.sky,
                child: Column(
                  children: [
                    _kvRow("Savdo tushum", formatUzs(asDouble(kpis['revenue']))),
                    const SizedBox(height: 6),
                    _kvRow(
                      "Sof foyda",
                      "${formatUzs(asDouble(kpis['profit']))} (${asDouble(kpis['margin_pct']).toStringAsFixed(1)}%)",
                      valueColor: NorinPalette.profit,
                    ),
                    const SizedBox(height: 6),
                    _kvRow("Sotuvlar / Vazn", "${asInt(kpis['sales_count'])} ta • ${formatKg(asDouble(kpis['total_kg']))}"),
                    const SizedBox(height: 6),
                    _kvRow("Xarajatlar", formatUzs(asDouble(kpis['expenses'])), valueColor: NorinPalette.amber),
                    const SizedBox(height: 6),
                    _kvRow("Kassa qoldig'i", formatUzs(asDouble(cash['expected_balance']))),
                  ],
                ),
              ),
              if (sales.isNotEmpty) ...[
                const SizedBox(height: 14),
                Text(
                  "Sotuvlar (${sales.length})",
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 6),
                Card(
                  child: Column(
                    children: [
                      for (int i = 0; i < sales.length; i++) ...[
                        if (i > 0) const Divider(),
                        ListTile(
                          dense: true,
                          title: Text(
                            asStr(sales[i]['client_name'], "Sotuv #${asInt(sales[i]['id'])}"),
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                          subtitle: Text(formatKg(asDouble(sales[i]['total_weight_kg']))),
                          trailing: Text(
                            formatUzs(asDouble(sales[i]['total_amount'])),
                            style: tNumStyle.copyWith(fontWeight: FontWeight.w700),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
              if (payments.isNotEmpty) ...[
                const SizedBox(height: 14),
                Text(
                  "To'lovlar (${payments.length})",
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 6),
                Card(
                  child: Column(
                    children: [
                      for (int i = 0; i < payments.length; i++) ...[
                        if (i > 0) const Divider(),
                        ListTile(
                          dense: true,
                          title: Text(
                            asStr(payments[i]['client_name'], "Mijoz #${asInt(payments[i]['client_id'])}"),
                            style: const TextStyle(fontWeight: FontWeight.w600),
                          ),
                          subtitle: Text(formatPaymentMethod(asStr(payments[i]['payment_method']))),
                          trailing: Text(
                            formatUzs(asDouble(payments[i]['amount'])),
                            style: tNumStyle.copyWith(
                              color: NorinPalette.profit,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ],
          );
        },
      ),
    );
  }

  Widget _kvRow(String label, String value, {Color? valueColor}) {
    return Row(
      children: [
        Text(label, style: const TextStyle(fontSize: 13)),
        const Spacer(),
        Text(
          value,
          style: tNumStyle.copyWith(
            fontWeight: FontWeight.w800,
            fontSize: 13.5,
            color: valueColor,
          ),
        ),
      ],
    );
  }
}
