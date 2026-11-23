import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/metric_cards.dart';
import '../../core/widgets/norin_widgets.dart';
import '../sales/sale_sheets.dart';

final clientDetailProvider =
    FutureProvider.autoDispose.family<Map<String, dynamic>, int>((ref, clientId) async {
  final api = ref.read(apiClientProvider);
  final card = asMap(await api.get('/clients/$clientId'));
  final statement = asMap(await api.get('/clients/$clientId/statement'));
  return {'card': card, 'statement': statement};
});

class ClientDetailScreen extends ConsumerStatefulWidget {
  const ClientDetailScreen({super.key, required this.clientId, required this.initialName});
  final int clientId;
  final String initialName;

  @override
  ConsumerState<ClientDetailScreen> createState() => _ClientDetailScreenState();
}

class _ClientDetailScreenState extends ConsumerState<ClientDetailScreen> {
  int _tab = 0; // 0 = Akt Sverka, 1 = Operatsiyalar

  void _refresh() {
    ref.invalidate(clientDetailProvider(widget.clientId));
    invalidateOperationalData(ref);
  }

  Future<void> _addPaymentDialog(Map<String, dynamic> card) async {
    final amountCtrl = TextEditingController();
    final noteCtrl = TextEditingController();
    String method = 'cash';
    bool postGroup = card['group_chat_id'] != null;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          title: Text("Pul olish — ${asStr(card['name'])}"),
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
                const SizedBox(height: 12),
                TextField(
                  controller: noteCtrl,
                  decoration: const InputDecoration(labelText: "Izoh (ixtiyoriy)"),
                ),
                if (card['group_chat_id'] != null)
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
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Bekor")),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Saqlash")),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final amount = double.tryParse(amountCtrl.text.trim().replaceAll(',', '.'));
    if (amount == null || amount <= 0) {
      if (mounted) showSnack(context, "Summa 0 dan katta bo'lishi kerak", error: true);
      return;
    }
    try {
      final res = asMap(
        await ref.read(apiClientProvider).post(
          '/payments',
          data: {
            'client_id': widget.clientId,
            'amount': amount,
            'payment_method': method,
            'note': noteCtrl.text.trim(),
            'post_to_group': postGroup,
          },
        ),
      );
      _refresh();
      if (mounted) {
        showSnack(
          context,
          res['group_posted'] == true ? "To'lov qayd etildi va guruhga yuborildi" : "To'lov saqlandi",
        );
      }
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  }

  Future<void> _addReturnDialog(Map<String, dynamic> card) async {
    final products = ref.read(productsProvider).valueOrNull ?? const <Map<String, dynamic>>[];
    if (products.isEmpty) {
      showSnack(context, "Mahsulotlar topilmadi", error: true);
      return;
    }
    int pid = asInt(products.first['id']);
    final kgCtrl = TextEditingController();
    final reasonCtrl = TextEditingController();
    bool postGroup = card['group_chat_id'] != null;

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          title: Text("Vozvrat — ${asStr(card['name'])}"),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<int>(
                  key: ValueKey('ret_prod_$pid'),
                  initialValue: pid,
                  decoration: const InputDecoration(labelText: "Mahsulot"),
                  items: products
                      .map(
                        (p) => DropdownMenuItem<int>(
                          value: asInt(p['id']),
                          child: Text(asStr(p['name'])),
                        ),
                      )
                      .toList(),
                  onChanged: (v) => setDlg(() => pid = v ?? pid),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: kgCtrl,
                  keyboardType: const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(labelText: "Vazn / Miqdor *"),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: reasonCtrl,
                  decoration: const InputDecoration(labelText: "Sabab (ixtiyoriy)"),
                ),
                if (card['group_chat_id'] != null)
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
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Bekor")),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Saqlash")),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final kg = double.tryParse(kgCtrl.text.trim().replaceAll(',', '.'));
    if (kg == null || kg <= 0) {
      if (mounted) showSnack(context, "Vaznni to'g'ri kiriting", error: true);
      return;
    }
    try {
      await ref.read(apiClientProvider).post(
        '/returns',
        data: {
          'client_id': widget.clientId,
          'product_id': pid,
          'weight_kg': kg,
          'reason': reasonCtrl.text.trim(),
          'post_to_group': postGroup,
        },
      );
      _refresh();
      if (mounted) showSnack(context, "Vozvrat qayd etildi");
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  }

  Future<void> _customPricesDialog(Map<String, dynamic> card) async {
    final products = ref.read(productsProvider).valueOrNull ?? const <Map<String, dynamic>>[];
    final customPrices = asMap(card['custom_prices']);

    await showModalBottomSheet<void>(
      context: context,
      useSafeArea: true,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        top: false,
        child: ListView.separated(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
          itemCount: products.length + 1,
          separatorBuilder: (_, _) => const SizedBox(height: 8),
          itemBuilder: (ctx, i) {
            if (i == 0) {
              return Text(
                "Shaxsiy narxlar — ${asStr(card['name'])}",
                style: Theme.of(ctx).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
              );
            }
            final p = products[i - 1];
            final pid = asInt(p['id']);
            final customVal = customPrices['$pid'];
            final defVal = asDouble(p['default_sell_price']);
            return ListTile(
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
              tileColor: Theme.of(ctx).colorScheme.surfaceContainerHighest.withValues(alpha: 0.3),
              title: Text(asStr(p['name']), style: const TextStyle(fontWeight: FontWeight.w700)),
              subtitle: Text(
                customVal != null
                    ? "Shaxsiy: ${formatUzs(asDouble(customVal))} (Standart: ${formatUzs(defVal)})"
                    : "Standart: ${formatUzs(defVal)}",
              ),
              trailing: const Icon(Icons.edit_outlined),
              onTap: () async {
                final ctrl = TextEditingController(
                  text: customVal != null ? asDouble(customVal).round().toString() : '',
                );
                final act = await showDialog<String>(
                  context: ctx,
                  builder: (dCtx) => AlertDialog(
                    title: Text("${asStr(p['name'])} narxi"),
                    content: TextField(
                      controller: ctrl,
                      keyboardType: TextInputType.number,
                      decoration: InputDecoration(
                        labelText: "Shaxsiy sotuv narxi",
                        hintText: defVal.round().toString(),
                      ),
                    ),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(dCtx, 'reset'), child: const Text("Standartga")),
                      TextButton(onPressed: () => Navigator.pop(dCtx), child: const Text("Bekor")),
                      FilledButton(onPressed: () => Navigator.pop(dCtx, 'save'), child: const Text("Saqlash")),
                    ],
                  ),
                );
                if (act == null) return;
                try {
                  final val = act == 'reset' ? null : double.tryParse(ctrl.text.trim());
                  await ref.read(apiClientProvider).put(
                    '/clients/${widget.clientId}/prices/$pid',
                    data: {'sell_price': val},
                  );
                  _refresh();
                  if (ctx.mounted) Navigator.pop(ctx);
                  if (mounted) showSnack(context, "Narx yangilandi");
                } catch (e) {
                  if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
                }
              },
            );
          },
        ),
      ),
    );
  }

  Future<void> _editClientDialog(Map<String, dynamic> card) async {
    final nameCtrl = TextEditingController(text: asStr(card['name']));
    final phoneCtrl = TextEditingController(text: asStr(card['phone']));
    final debtCtrl = TextEditingController(text: asDouble(card['opening_debt']).round().toString());
    final aliasCtrl = TextEditingController(text: asStr(card['aliases']));

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Mijozni tahrirlash"),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: nameCtrl, decoration: const InputDecoration(labelText: "Nomi")),
              const SizedBox(height: 10),
              TextField(controller: phoneCtrl, decoration: const InputDecoration(labelText: "Telefon")),
              const SizedBox(height: 10),
              TextField(
                controller: debtCtrl,
                keyboardType: const TextInputType.numberWithOptions(signed: true),
                decoration: const InputDecoration(labelText: "Boshlang'ich qarz"),
              ),
              const SizedBox(height: 10),
              TextField(controller: aliasCtrl, decoration: const InputDecoration(labelText: "Aliases")),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Bekor")),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Saqlash")),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(apiClientProvider).patch(
        '/clients/${widget.clientId}',
        data: {
          'name': nameCtrl.text.trim(),
          'phone': phoneCtrl.text.trim(),
          'opening_debt': double.tryParse(debtCtrl.text.trim()) ?? 0,
          'aliases': aliasCtrl.text.trim(),
        },
      );
      _refresh();
      if (mounted) showSnack(context, "Mijoz ma'lumoti yangilandi");
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  }

  Future<void> _sendSverkaGroup() async {
    try {
      final res = asMap(
        await ref.read(apiClientProvider).post('/clients/${widget.clientId}/send-sverka'),
      );
      if (mounted) {
        showSnack(
          context,
          asStr(res['message'], res['posted'] == true ? "Sverka guruhga yuborildi" : "Yuborilmadi"),
          error: res['posted'] != true,
        );
      }
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final asyncDetail = ref.watch(clientDetailProvider(widget.clientId));

    return Scaffold(
      extendBodyBehindAppBar: false,
      appBar: AppBar(
        title: Text(widget.initialName, style: const TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          IconButton(
            tooltip: "Yangi sotuv",
            icon: const Icon(Icons.add_shopping_cart_rounded),
            onPressed: () => openNewSaleSheet(context, ref, initialClientId: widget.clientId),
          ),
          SpinningRefreshButton(
            onRefresh: () async {
              _refresh();
              await ref
                  .read(clientDetailProvider(widget.clientId).future)
                  .catchError((_) => <String, dynamic>{});
            },
          ),
        ],
      ),
      body: CosmicBackground(
        child: asyncDetail.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => AsyncErrorCard(error: e, onRetry: _refresh),
        data: (bundle) {
          final card = asMap(bundle['card']);
          final statement = asMap(bundle['statement']);
          final events = asMapList(statement['events']);
          final recentSales = asMapList(card['recent_sales']);
          final recentPayments = asMapList(card['recent_payments']);
          final recentReturns = asMapList(card['recent_returns']);
          final debt = asDouble(card['current_debt']);
          final hasGroup = card['group_chat_id'] != null;

          return RefreshIndicator(
            onRefresh: () async => _refresh(),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 40),
              children: [
                SpotlightHeroCard(
                  padding: const EdgeInsets.all(18),
                  borderRadius: 20,
                  glowColor: debt > 0 ? NorinPalette.danger : NorinPalette.emeraldLight,
                  accentColor: NorinPalette.indigo,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text(
                            debt > 0 ? "JORIY QARZ" : (debt < 0 ? "AVANS / HAQI" : "BALANS TOZA"),
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                              fontSize: 11.5,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.7,
                            ),
                          ),
                          const Spacer(),
                          IconButton(
                            tooltip: "Tahrirlash",
                            visualDensity: VisualDensity.compact,
                            icon: const Icon(Icons.edit_outlined),
                            onPressed: () => _editClientDialog(card),
                          ),
                        ],
                      ),
                      Text(
                        formatUzs(debt),
                        style: tNumStyle.copyWith(
                          fontSize: 28,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        "Savdo: ${formatCompactUzs(asDouble(card['total_sales']))}  •  To'lov: ${formatCompactUzs(asDouble(card['total_payments']))}  •  Vozvrat: ${formatCompactUzs(asDouble(card['total_returns']))}",
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                          fontSize: 12,
                        ),
                      ),
                      if (hasGroup) ...[
                        const SizedBox(height: 8),
                        Row(
                          children: [
                            const Icon(Icons.groups_rounded, size: 16, color: NorinPalette.emerald),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(
                                asStr(card['group_title'], "Guruh #${card['group_chat_id']}"),
                                style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12.5),
                              ),
                            ),
                            TextButton(
                              style: TextButton.styleFrom(
                                visualDensity: VisualDensity.compact,
                              ),
                              onPressed: () async {
                                final yes = await showConfirmDialog(
                                  context,
                                  title: "Guruhni uzish",
                                  message: "Bu mijozdan Telegram guruhi uzilsinmi?",
                                  destructive: true,
                                );
                                if (!yes) return;
                                await ref
                                    .read(apiClientProvider)
                                    .post('/clients/${widget.clientId}/unbind-group');
                                _refresh();
                              },
                              child: const Text("Uzish"),
                            ),
                          ],
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    FilledButton.icon(
                      onPressed: () => _addPaymentDialog(card),
                      icon: const Icon(Icons.payments_outlined),
                      label: const Text("Pul oldim"),
                    ),
                    FilledButton.tonalIcon(
                      onPressed: () => _addReturnDialog(card),
                      icon: const Icon(Icons.assignment_return_outlined),
                      label: const Text("Vozvrat"),
                    ),
                    OutlinedButton.icon(
                      onPressed: () => _customPricesDialog(card),
                      icon: const Icon(Icons.price_change_outlined),
                      label: const Text("Narxlar"),
                    ),
                    OutlinedButton.icon(
                      onPressed: () => showExcelActionPicker(
                        context,
                        ref.read(apiClientProvider),
                        title: "Akt Sverka Excel",
                        path: '/export/client/${widget.clientId}',
                        filename: 'Sverka_${asStr(card['name'])}.xlsx',
                      ),
                      icon: const Icon(Icons.table_chart_outlined),
                      label: const Text("Excel"),
                    ),
                    if (hasGroup)
                      OutlinedButton.icon(
                        onPressed: _sendSverkaGroup,
                        icon: const Icon(Icons.send_rounded),
                        label: const Text("Guruhga Sverka"),
                      ),
                  ],
                ),
                const SizedBox(height: 16),
                SegmentedButton<int>(
                  showSelectedIcon: false,
                  segments: [
                    ButtonSegment(value: 0, label: Text("Akt Sverka (${events.length})")),
                    ButtonSegment(
                      value: 1,
                      label: Text("Operatsiyalar (${recentSales.length + recentPayments.length + recentReturns.length})"),
                    ),
                  ],
                  selected: {_tab},
                  onSelectionChanged: (s) => setState(() => _tab = s.first),
                ),
                const SizedBox(height: 12),
                if (_tab == 0)
                  if (events.isEmpty)
                    const EmptyStateCard(
                      icon: Icons.receipt_long_outlined,
                      title: "Hali harakatlar yo'q",
                    )
                  else
                    Card(
                      child: Column(
                        children: [
                          for (int i = events.length - 1; i >= 0; i--) ...[
                            if (i < events.length - 1) const Divider(),
                            _StatementTile(ev: events[i]),
                          ],
                        ],
                      ),
                    )
                else ...[
                  if (recentSales.isEmpty && recentPayments.isEmpty && recentReturns.isEmpty)
                    const EmptyStateCard(
                      icon: Icons.history_outlined,
                      title: "So'nggi operatsiyalar yo'q",
                    ),
                  for (final s in recentSales) ...[
                    Card(
                      child: ListTile(
                        leading: const CircleAvatar(
                          backgroundColor: Color(0x1A0284C7),
                          child: Icon(Icons.shopping_bag_outlined, color: NorinPalette.sky),
                        ),
                        title: Text(
                          "Sotuv #${asInt(s['id'])} • ${formatKg(asDouble(s['total_weight_kg']))}",
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        subtitle: Text(formatLocalDateTime(asStr(s['created_at']))),
                        trailing: Text(
                          formatUzs(asDouble(s['total_amount'])),
                          style: tNumStyle.copyWith(fontWeight: FontWeight.w800),
                        ),
                        onTap: () => openSaleReviewSheet(context, ref, s),
                      ),
                    ),
                    const SizedBox(height: 6),
                  ],
                  for (final p in recentPayments) ...[
                    Card(
                      child: ListTile(
                        leading: const CircleAvatar(
                          backgroundColor: Color(0x1A059669),
                          child: Icon(Icons.payments_outlined, color: NorinPalette.profit),
                        ),
                        title: Text(
                          "To'lov (${asStr(p['payment_method'])})",
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        subtitle: Text(formatLocalDateTime(asStr(p['created_at']))),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              "-${formatUzs(asDouble(p['amount']))}",
                              style: tNumStyle.copyWith(
                                color: NorinPalette.profit,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete_outline, color: NorinPalette.danger, size: 20),
                              onPressed: () async {
                                final yes = await showConfirmDialog(
                                  context,
                                  title: "To'lovni o'chirish",
                                  message: "Bu to'lov o'chirilsinmi?",
                                  destructive: true,
                                );
                                if (!yes) return;
                                await ref.read(apiClientProvider).delete('/payments/${asInt(p['id'])}');
                                _refresh();
                              },
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 6),
                  ],
                  for (final r in recentReturns) ...[
                    Card(
                      child: ListTile(
                        leading: const CircleAvatar(
                          backgroundColor: Color(0x1AF59E0B),
                          child: Icon(Icons.assignment_return_outlined, color: NorinPalette.amber),
                        ),
                        title: Text(
                          "Vozvrat: ${asStr(r['product_name'], 'Mahsulot')} (${formatKg(asDouble(r['weight_kg']))})",
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        subtitle: Text(formatLocalDateTime(asStr(r['created_at']))),
                        trailing: IconButton(
                          icon: const Icon(Icons.delete_outline, color: NorinPalette.danger, size: 20),
                          onPressed: () async {
                            final yes = await showConfirmDialog(
                              context,
                              title: "Vozvratni o'chirish",
                              message: "Bu vozvrat o'chirilsinmi?",
                              destructive: true,
                            );
                            if (!yes) return;
                            await ref.read(apiClientProvider).delete('/returns/${asInt(r['id'])}');
                            _refresh();
                          },
                        ),
                      ),
                    ),
                    const SizedBox(height: 6),
                  ],
                ],
              ],
            ),
          );
        },
      ),
      ),
    );
  }
}

class _StatementTile extends StatelessWidget {
  const _StatementTile({required this.ev});
  final Map<String, dynamic> ev;

  @override
  Widget build(BuildContext context) {
    final kind = asStr(ev['kind']);
    final debit = asDouble(ev['debit']);
    final credit = asDouble(ev['credit']);
    final bal = asDouble(ev['balance']);
    final (Color col, IconData ic) = switch (kind) {
      'sale' => (NorinPalette.sky, Icons.add_circle_outline),
      'payment' => (NorinPalette.profit, Icons.payments_outlined),
      _ => (NorinPalette.amber, Icons.assignment_return_outlined),
    };
    final amountText = debit > 0 ? "+${formatCompactUzs(debit)}" : "-${formatCompactUzs(credit)}";

    return ListTile(
      dense: true,
      leading: Icon(ic, color: col),
      title: Text(
        "${asStr(ev['doc'])} • ${asStr(ev['detail'])}",
        maxLines: 2,
        overflow: TextOverflow.ellipsis,
        style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
      ),
      subtitle: Text(formatLocalDateTime(asStr(ev['at'])), style: const TextStyle(fontSize: 11)),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(
            amountText,
            style: tNumStyle.copyWith(color: col, fontWeight: FontWeight.w800, fontSize: 13),
          ),
          Text(
            "Bal: ${formatCompactUzs(bal)}",
            style: tNumStyle.copyWith(fontSize: 11, fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}
