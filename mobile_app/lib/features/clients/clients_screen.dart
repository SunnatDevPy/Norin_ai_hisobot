import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/metric_cards.dart';
import '../../core/widgets/norin_widgets.dart';
import 'client_detail_screen.dart';

class ClientsScreen extends ConsumerStatefulWidget {
  const ClientsScreen({super.key});

  @override
  ConsumerState<ClientsScreen> createState() => _ClientsScreenState();
}

class _ClientsScreenState extends ConsumerState<ClientsScreen> {
  final _searchCtrl = TextEditingController();
  String _filter = 'all'; // all | debt | group

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
          'opening_debt': double.tryParse(debtCtrl.text.trim()) ?? 0,
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
        title: const Text("Mijozlar & Qarzlar", style: TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          IconButton(
            tooltip: "Yangi mijoz",
            icon: const Icon(Icons.person_add_alt_1_rounded),
            onPressed: _showAddClientDialog,
          ),
          IconButton(
            tooltip: "Yangilash",
            icon: const Icon(Icons.refresh_rounded),
            onPressed: () => ref.invalidate(clientsProvider),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(clientsProvider);
          await ref.read(clientsProvider.future);
        },
        child: clientsAsync.when(
          loading: () => const Center(child: CircularProgressIndicator()),
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
              if (_filter == 'group' && c['group_chat_id'] == null) return false;
              return true;
            }).toList();

            final totalDebt = clients.fold<double>(
              0,
              (sum, c) => sum + (asDouble(c['current_debt']) > 0 ? asDouble(c['current_debt']) : 0),
            );
            final debtorsCount = clients.where((c) => asDouble(c['current_debt']) > 0).length;

            return ListView(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 120),
              children: [
                SpotlightHeroCard(
                  padding: const EdgeInsets.all(16),
                  borderRadius: 20,
                  glowColor: NorinPalette.emeraldLight,
                  accentColor: NorinPalette.indigo,
                  child: Row(
                    children: [
                      const Icon(Icons.account_balance_wallet_outlined, color: Colors.white, size: 30),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              "Jami mijozlar qarzi",
                              style: TextStyle(color: Colors.white70, fontSize: 12, fontWeight: FontWeight.w600),
                            ),
                            Text(
                              formatUzs(totalDebt),
                              style: tNumStyle.copyWith(
                                color: Colors.white,
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
                          color: Colors.white.withValues(alpha: 0.14),
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Text(
                          "$debtorsCount qarzdor / ${clients.length}",
                          style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w700),
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
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  children: [
                    ChoiceChip(
                      label: Text("Hammasi (${clients.length})"),
                      selected: _filter == 'all',
                      onSelected: (_) => setState(() => _filter = 'all'),
                    ),
                    ChoiceChip(
                      label: Text("Qarzdorlar ($debtorsCount)"),
                      selected: _filter == 'debt',
                      onSelected: (_) => setState(() => _filter = 'debt'),
                    ),
                    ChoiceChip(
                      label: const Text("Guruhli"),
                      selected: _filter == 'group',
                      onSelected: (_) => setState(() => _filter = 'group'),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
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
                    const SizedBox(height: 8),
                  ],
              ],
            );
          },
        ),
      ),
    );
  }
}

class _ClientCard extends StatelessWidget {
  const _ClientCard({required this.client, required this.onTap});
  final Map<String, dynamic> client;
  final VoidCallback onTap;

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
          padding: const EdgeInsets.all(14),
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
            ],
          ),
        ),
      ),
    );
  }
}
