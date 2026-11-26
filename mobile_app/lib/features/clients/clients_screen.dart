import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/metric_cards.dart';
import '../../core/widgets/norin_widgets.dart';
import '../cash/cash_screen.dart';
import 'client_detail_screen.dart';

class ClientsScreen extends ConsumerStatefulWidget {
  const ClientsScreen({super.key});

  @override
  ConsumerState<ClientsScreen> createState() => _ClientsScreenState();
}

class _ClientsScreenState extends ConsumerState<ClientsScreen> {
  final _searchCtrl = TextEditingController();
  String _filter = 'all'; // all | debt | advance | group
  bool _sortByDebt = true;

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _showAddClientDialog() async {
    final nameCtrl = TextEditingController();
    final phoneCtrl = TextEditingController();
    final debtCtrl = TextEditingController(text: '0');
    final aliasCtrl = TextEditingController();

    final created = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Yangi mijoz"),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameCtrl,
                decoration: const InputDecoration(labelText: "Nomi *"),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: phoneCtrl,
                keyboardType: TextInputType.phone,
                decoration: const InputDecoration(labelText: "Telefon (+998...)"),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: debtCtrl,
                keyboardType: const TextInputType.numberWithOptions(signed: true),
                decoration: const InputDecoration(labelText: "Boshlang'ich qarz (so'm)"),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: aliasCtrl,
                decoration: const InputDecoration(labelText: "Qisqa nomlar (aliases)"),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Bekor")),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Qo'shish")),
        ],
      ),
    );
    if (created != true) return;
    final name = nameCtrl.text.trim();
    if (name.isEmpty) {
      if (mounted) showSnack(context, "Mijoz nomini kiriting", error: true);
      return;
    }
    try {
      await ref.read(apiClientProvider).post(
        '/clients',
        data: {
          'name': name,
          'phone': phoneCtrl.text.trim(),
          'opening_debt': parseNumberInput(debtCtrl.text) ?? 0,
          'aliases': aliasCtrl.text.trim(),
        },
      );
      invalidateOperationalData(ref);
      if (mounted) showSnack(context, "Mijoz \"$name\" qo'shildi");
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final clientsAsync = ref.watch(clientsProvider);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: const Text("Mijozlar", style: TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          IconButton(
            tooltip: _sortByDebt ? "Tartib: Qarz bo'yicha (A-Z ga o'tish)" : "Tartib: A-Z (Qarz bo'yicha)",
            icon: Icon(_sortByDebt ? Icons.sort_rounded : Icons.sort_by_alpha_rounded),
            onPressed: () {
              setState(() => _sortByDebt = !_sortByDebt);
              showSnack(
                context,
                _sortByDebt ? "Tartib: Eng katta qarzdan" : "Tartib: Alifbo (A-Z)",
              );
            },
          ),
          IconButton(
            tooltip: "Yangi mijoz",
            icon: const Icon(Icons.person_add_alt_1_rounded),
            onPressed: _showAddClientDialog,
          ),
          SpinningRefreshButton(
            onRefresh: () async {
              ref.invalidate(clientsProvider);
              await ref.read(clientsProvider.future).catchError((_) => <Map<String, dynamic>>[]);
            },
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(clientsProvider);
          await ref.read(clientsProvider.future);
        },
        child: clientsAsync.when(
          loading: () => const _ClientsSkeleton(),
          error: (e, _) => AsyncErrorCard(
            error: e,
            onRetry: () => ref.invalidate(clientsProvider),
          ),
          data: (clients) {
            final q = _searchCtrl.text.trim().toLowerCase();
            final filtered = clients.where((c) {
              final name = asStr(c['name']).toLowerCase();
              final phone = asStr(c['phone']).toLowerCase();
              final aliases = asStr(c['aliases']).toLowerCase();
              if (q.isNotEmpty && !name.contains(q) && !phone.contains(q) && !aliases.contains(q)) {
                return false;
              }
              final debt = asDouble(c['current_debt']);
              if (_filter == 'debt' && debt <= 0) return false;
              if (_filter == 'advance' && debt >= 0) return false;
              if (_filter == 'group' && c['group_chat_id'] == null) return false;
              return true;
            }).toList();

            if (_sortByDebt) {
              filtered.sort((a, b) => asDouble(b['current_debt']).compareTo(asDouble(a['current_debt'])));
            } else {
              filtered.sort(
                (a, b) => asStr(a['name']).toLowerCase().compareTo(asStr(b['name']).toLowerCase()),
              );
            }

            final totalDebt = clients.fold<double>(
              0,
              (sum, c) => sum + (asDouble(c['current_debt']) > 0 ? asDouble(c['current_debt']) : 0),
            );
            final debtorsCount = clients.where((c) => asDouble(c['current_debt']) > 0).length;
            final advanceCount = clients.where((c) => asDouble(c['current_debt']) < 0).length;

            return ListView(
              padding: EdgeInsets.fromLTRB(16, 8, 16, dockBottomClearance(context)),
              children: [
                SpotlightHeroCard(
                  padding: const EdgeInsets.all(16),
                  borderRadius: 20,
                  glowColor: NorinPalette.emeraldLight,
                  accentColor: NorinPalette.indigo,
                  child: Row(
                    children: [
                      const Icon(
                        Icons.account_balance_wallet_outlined,
                        color: NorinPalette.emerald,
                        size: 30,
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              "Jami qarz",
                              style: TextStyle(
                                color: Theme.of(context).colorScheme.onSurfaceVariant,
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            AnimatedCountText(
                              key: ValueKey('debt_${ref.watch(refreshEpochProvider)}'),
                              value: totalDebt,
                              formatter: formatUzs,
                              style: tNumStyle.copyWith(
                                fontSize: 21,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                          ],
                        ),
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                        decoration: BoxDecoration(
                          color: NorinPalette.emerald.withValues(alpha: 0.15),
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Text(
                          "$debtorsCount qarzdor / ${clients.length}",
                          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _searchCtrl,
                  onChanged: (_) => setState(() {}),
                  decoration: InputDecoration(
                    hintText: "Mijoz ismi yoki telefon bo'yicha qidirish...",
                    prefixIcon: const Icon(Icons.search_rounded),
                    suffixIcon: q.isNotEmpty
                        ? IconButton(
                            icon: const Icon(Icons.clear_rounded),
                            onPressed: () {
                              _searchCtrl.clear();
                              setState(() {});
                            },
                          )
                        : null,
                  ),
                ),
                const SizedBox(height: 12),
                SizedBox(
                  height: 40,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    children: [
                      ChoiceChip(
                        label: Text("Hammasi (${clients.length})"),
                        selected: _filter == 'all',
                        onSelected: (_) => setState(() => _filter = 'all'),
                      ),
                      const SizedBox(width: 8),
                      ChoiceChip(
                        label: Text("Qarzdorlar ($debtorsCount)"),
                        selected: _filter == 'debt',
                        onSelected: (_) => setState(() => _filter = 'debt'),
                      ),
                      if (advanceCount > 0) ...[
                        const SizedBox(width: 8),
                        ChoiceChip(
                          label: Text("Avans ($advanceCount)"),
                          selected: _filter == 'advance',
                          onSelected: (_) => setState(() => _filter = 'advance'),
                        ),
                      ],
                      const SizedBox(width: 8),
                      ChoiceChip(
                        label: const Text("Guruhli"),
                        selected: _filter == 'group',
                        onSelected: (_) => setState(() => _filter = 'group'),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),
                if (filtered.isEmpty)
                  EmptyStateCard(
                    icon: Icons.people_outline_rounded,
                    title: "Mijoz topilmadi",
                    action: FilledButton.icon(
                      onPressed: _showAddClientDialog,
                      icon: const Icon(Icons.add),
                      label: const Text("Mijoz qo'shish"),
                    ),
                  )
                else
                  for (final c in filtered) ...[
                    _ClientCard(
                      client: c,
                      onQuickPay: asDouble(c['current_debt']) > 0
                          ? () => openQuickPaymentDialog(
                                context,
                                ref,
                                initialClientId: asInt(c['id']),
                              )
                          : null,
                      onTap: () async {
                        await Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => ClientDetailScreen(
                              clientId: asInt(c['id']),
                              initialName: asStr(c['name']),
                            ),
                          ),
                        );
                        invalidateOperationalData(ref);
                      },
                    ),
                    const SizedBox(height: 10),
                  ],
              ],
            );
          },
        ),
      ),
    );
  }
}

class _ClientsSkeleton extends StatelessWidget {
  const _ClientsSkeleton();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: EdgeInsets.fromLTRB(16, 8, 16, dockBottomClearance(context)),
      children: const [
        CosmicShimmerBox(height: 82, borderRadius: 20),
        SizedBox(height: 12),
        CosmicShimmerBox(height: 52, borderRadius: 16),
        SizedBox(height: 12),
        CosmicShimmerBox(height: 74, borderRadius: 18),
        SizedBox(height: 8),
        CosmicShimmerBox(height: 74, borderRadius: 18),
        SizedBox(height: 8),
        CosmicShimmerBox(height: 74, borderRadius: 18),
      ],
    );
  }
}

class _ClientCard extends StatelessWidget {
  const _ClientCard({
    required this.client,
    required this.onTap,
    this.onQuickPay,
  });

  final Map<String, dynamic> client;
  final VoidCallback onTap;
  final VoidCallback? onQuickPay;

  @override
  Widget build(BuildContext context) {
    final name = asStr(client['name'], 'Mijoz');
    final phone = asStr(client['phone']);
    final debt = asDouble(client['current_debt']);
    final hasGroup = client['group_chat_id'] != null;
    final letter = name.isNotEmpty ? name[0].toUpperCase() : '?';

    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(
            children: [
              CircleAvatar(
                radius: 22,
                backgroundColor: NorinPalette.emerald.withValues(alpha: 0.14),
                child: Text(
                  letter,
                  style: const TextStyle(
                    color: NorinPalette.emerald,
                    fontWeight: FontWeight.w800,
                    fontSize: 16,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Flexible(
                          child: Text(
                            name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
                          ),
                        ),
                        if (hasGroup) ...[
                          const SizedBox(width: 6),
                          const Icon(Icons.verified_rounded, size: 15, color: NorinPalette.sky),
                        ],
                      ],
                    ),
                    const SizedBox(height: 3),
                    Text(
                      phone.isNotEmpty
                          ? phone
                          : (hasGroup ? asStr(client['group_title'], 'Guruh ulangan') : "Telefon kiritilmagan"),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 12,
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    debt == 0 ? "0 so'm" : formatCompactUzs(debt),
                    style: tNumStyle.copyWith(
                      fontWeight: FontWeight.w900,
                      fontSize: 14.5,
                      color: debt > 0
                          ? NorinPalette.danger
                          : (debt < 0 ? NorinPalette.profit : null),
                    ),
                  ),
                  Text(
                    debt > 0 ? "Qarz" : (debt < 0 ? "Avans" : "Toza"),
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: debt > 0 ? NorinPalette.danger : NorinPalette.profit,
                    ),
                  ),
                ],
              ),
              if (onQuickPay != null) ...[
                const SizedBox(width: 6),
                IconButton(
                  tooltip: "Tez pul olish",
                  visualDensity: VisualDensity.compact,
                  style: IconButton.styleFrom(
                    backgroundColor: NorinPalette.profit.withValues(alpha: 0.14),
                    foregroundColor: NorinPalette.profit,
                  ),
                  icon: const Icon(Icons.payments_outlined, size: 18),
                  onPressed: onQuickPay,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
