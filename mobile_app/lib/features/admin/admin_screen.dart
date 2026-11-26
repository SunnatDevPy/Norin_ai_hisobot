import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/utils/formatters.dart';
import '../../core/widgets/metric_cards.dart';
import '../../core/widgets/norin_widgets.dart';
import '../shell/main_shell.dart';

class AdminScreen extends ConsumerStatefulWidget {
  const AdminScreen({super.key, this.initialTab = 0});

  final int initialTab;

  @override
  ConsumerState<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends ConsumerState<AdminScreen> with SingleTickerProviderStateMixin {
  late final TabController _tabs;
  final _broadcastCtrl = TextEditingController();
  bool _sendingBroadcast = false;
  List<Map<String, dynamic>>? _auditLogs;
  bool _loadingAudit = false;

  @override
  void initState() {
    super.initState();
    _tabs = TabController(
      length: 3,
      vsync: this,
      initialIndex: widget.initialTab.clamp(0, 2),
    );
    _tabs.addListener(() {
      if (_tabs.index == 2 && _auditLogs == null && !_loadingAudit) {
        _loadAudit();
      }
    });
  }

  @override
  void dispose() {
    _tabs.dispose();
    _broadcastCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadAudit() async {
    setState(() => _loadingAudit = true);
    try {
      final list = asMapList(await ref.read(apiClientProvider).get('/admin/audit'));
      if (mounted) setState(() => _auditLogs = list);
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _loadingAudit = false);
    }
  }

  Future<void> _createTenantDialog() async {
    final nameCtrl = TextEditingController();
    final priceCtrl = TextEditingController(text: '300000');
    final daysCtrl = TextEditingController(text: '30');
    final ownerTgCtrl = TextEditingController();
    final ownerNameCtrl = TextEditingController();

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Yangi do'kon"),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: nameCtrl, decoration: const InputDecoration(labelText: "Do'kon nomi *")),
              const SizedBox(height: 10),
              TextField(
                controller: priceCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: "Oylik narx (so'm)"),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: daysCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: "Sinov kunlari"),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: ownerTgCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: "Egasi Telegram ID (ixtiyoriy)"),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: ownerNameCtrl,
                decoration: const InputDecoration(labelText: "Egasi ismi (ixtiyoriy)"),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Bekor")),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Yaratish")),
        ],
      ),
    );
    if (ok != true) return;
    final name = nameCtrl.text.trim();
    if (name.isEmpty) {
      if (mounted) showSnack(context, "Do'kon nomini kiriting", error: true);
      return;
    }
    try {
      final api = ref.read(apiClientProvider);
      final created = asMap(
        await api.post(
          '/admin/tenants',
          data: {
            'tenant_name': name,
            'monthly_price': double.tryParse(priceCtrl.text.trim()) ?? 300000,
            'trial_days': int.tryParse(daysCtrl.text.trim()) ?? 30,
          },
        ),
      );
      final newTid = asInt(created['id']);
      final ownerTg = int.tryParse(ownerTgCtrl.text.trim());
      if (newTid > 0 && ownerTg != null && ownerTg > 0) {
        await api.post(
          '/admin/users',
          data: {
            'telegram_id': ownerTg,
            'full_name': ownerNameCtrl.text.trim(),
            'role': 'owner',
            'tenant_id': newTid,
          },
        );
      }
      ref.invalidate(adminTenantsProvider);
      ref.invalidate(adminAnalyticsProvider);
      if (mounted) showSnack(context, "Do'kon \"$name\" yaratildi");
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  }

  Future<void> _sendBroadcast() async {
    final txt = _broadcastCtrl.text.trim();
    if (txt.isEmpty) {
      showSnack(context, "E'lon matnini kiriting", error: true);
      return;
    }
    final yes = await showConfirmDialog(
      context,
      title: "Barchaga e'lon",
      message: "Xabar barcha faol foydalanuvchilarga yuborilsinmi?",
      confirmLabel: "Yuborish",
    );
    if (!yes) return;
    setState(() => _sendingBroadcast = true);
    try {
      final res = asMap(
        await ref.read(apiClientProvider).post('/admin/broadcast', data: {'text': txt}),
      );
      _broadcastCtrl.clear();
      await _loadAudit();
      if (mounted) {
        showSnack(
          context,
          "Yuborildi: ${asInt(res['sent'])} / ${asInt(res['total'])} ta",
        );
      }
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _sendingBroadcast = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    if (!auth.isSuperAdmin) {
      return const Scaffold(body: Center(child: Text("Faqat Super Admin uchun")));
    }

    final analyticsAsync = ref.watch(adminAnalyticsProvider);
    final tenantsAsync = ref.watch(adminTenantsProvider);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: const Text("Admin Panel", style: TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          SpinningRefreshButton(
            onRefresh: () async {
              ref.invalidate(adminAnalyticsProvider);
              ref.invalidate(adminTenantsProvider);
              await Future.wait<Object?>([
                ref.read(adminAnalyticsProvider.future),
                ref.read(adminTenantsProvider.future),
                _loadAudit(),
              ]).catchError((_) => <Object?>[]);
            },
          ),
        ],
        bottom: TabBar(
          controller: _tabs,
          tabs: const [
            Tab(icon: Icon(Icons.insights_rounded), text: "Statistika"),
            Tab(icon: Icon(Icons.store_mall_directory_rounded), text: "Do'konlar"),
            Tab(icon: Icon(Icons.campaign_rounded), text: "Tarix"),
          ],
        ),
      ),
      body: CosmicBackground(
        child: TabBarView(
          controller: _tabs,
          children: [
          // 1. Statistika / MRR
          RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(adminAnalyticsProvider);
              await ref.read(adminAnalyticsProvider.future);
            },
            child: analyticsAsync.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => AsyncErrorCard(
                error: e,
                onRetry: () => ref.invalidate(adminAnalyticsProvider),
              ),
              data: (an) {
                final mrr = asDouble(an['paying_mrr']);
                final totalTenants = asInt(an['total_tenants']);
                final payingT = asInt(an['paying_tenants']);
                final sc = asMap(an['status_counts']);
                final aiG = asMap(an['ai_global']);
                final activeT = asInt(sc['active']) + asInt(sc['expiring']) + asInt(sc['grace']);
                final expT = asInt(sc['expired']);
                final suspT = asInt(sc['suspended']);
                final col30 = asDouble(an['collected_30d']);
                final colAll = asDouble(an['collected_all']);
                final aiCalls = asInt(aiG['total_calls']);
                final aiTokens = asInt(aiG['total_tokens']);

                return ListView(
                  padding: EdgeInsets.fromLTRB(
                    16,
                    12,
                    16,
                    screenBottomClearance(context, extra: 28),
                  ),
                  children: [
                    SpotlightHeroCard(
                      padding: const EdgeInsets.all(20),
                      borderRadius: 22,
                      glowColor: NorinPalette.indigo,
                      accentColor: NorinPalette.emeraldLight,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            "OYLIK MRR ($payingT PULLIK DO'KON)",
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.6,
                            ),
                          ),
                          const SizedBox(height: 6),
                          AnimatedCountText(
                            value: mrr,
                            formatter: formatUzs,
                            style: tNumStyle.copyWith(
                              fontSize: 28,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                          const SizedBox(height: 10),
                          Text(
                            "Jami: $totalTenants • Faol: $activeT • Tugagan: $expT • Blok: $suspT",
                            style: TextStyle(
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                              fontSize: 12,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),
                    GridView.count(
                      crossAxisCount: 2,
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      mainAxisSpacing: 10,
                      crossAxisSpacing: 10,
                      childAspectRatio: 1.5,
                      children: [
                        KpiCardTile(
                          title: "30 kunlik yig'im",
                          value: formatCompactUzs(col30),
                          numericValue: col30,
                          valueFormatter: formatCompactUzs,
                          subtitle: formatUzs(col30),
                          icon: Icons.payments_outlined,
                          color: NorinPalette.profit,
                        ),
                        KpiCardTile(
                          title: "Jami SaaS tushumi",
                          value: formatCompactUzs(colAll),
                          numericValue: colAll,
                          valueFormatter: formatCompactUzs,
                          subtitle: formatUzs(colAll),
                          icon: Icons.account_balance_rounded,
                          color: NorinPalette.indigo,
                        ),
                        KpiCardTile(
                          title: "AI so'rovlar (30k)",
                          value: "$aiCalls ta",
                          subtitle: "Jami: ${asInt(an['total_sales'])} sotuv",
                          icon: Icons.auto_awesome_rounded,
                          color: NorinPalette.emerald,
                        ),
                        KpiCardTile(
                          title: "AI Tokenlar (30k)",
                          value: formatCompactUzs(aiTokens.toDouble()).replaceAll(' ', ''),
                          subtitle: "$aiTokens token",
                          icon: Icons.memory_rounded,
                          color: NorinPalette.amber,
                        ),
                      ],
                    ),
                  ],
                );
              },
            ),
          ),

          // 2. Filiallar
          RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(adminTenantsProvider);
              await ref.read(adminTenantsProvider.future);
            },
            child: tenantsAsync.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => AsyncErrorCard(
                error: e,
                onRetry: () => ref.invalidate(adminTenantsProvider),
              ),
              data: (tenants) => ListView(
                padding: EdgeInsets.fromLTRB(
                  16,
                  12,
                  16,
                  screenBottomClearance(context, extra: 28),
                ),
                children: [
                  FilledButton.icon(
                    onPressed: _createTenantDialog,
                    icon: const Icon(Icons.add_business_rounded),
                    label: const Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text("Yangi do'kon qo'shish"),
                    ),
                  ),
                  const SizedBox(height: 12),
                  for (final t in tenants) ...[
                    _TenantAdminCard(
                      tenant: t,
                      isActiveSelected: asInt(t['id']) == auth.selectedTenantId,
                      onSwitch: () async {
                        await ref.read(authProvider.notifier).selectTenant(asInt(t['id']));
                        invalidateOperationalData(ref);
                        ref.read(shellTabIndexProvider.notifier).state = 0;
                        if (context.mounted) {
                          showSnack(context, "Tanlandi: ${asStr(t['tenant_name'] ?? t['name'])}");
                          if (Navigator.canPop(context)) {
                            Navigator.pop(context);
                          }
                        }
                      },
                      onManage: () async {
                        await showModalBottomSheet<void>(
                          context: context,
                          isScrollControlled: true,
                          useSafeArea: true,
                          showDragHandle: true,
                          builder: (_) => _TenantManageSheet(
                            tenant: t,
                            onChanged: () {
                              ref.invalidate(adminTenantsProvider);
                              ref.invalidate(adminAnalyticsProvider);
                              _loadAudit();
                            },
                          ),
                        );
                      },
                    ),
                    const SizedBox(height: 10),
                  ],
                ],
              ),
            ),
          ),

          // 3. Broadcast & Audit Log
          ListView(
            padding: EdgeInsets.fromLTRB(
              16,
              12,
              16,
              screenBottomClearance(context, extra: 28),
            ),
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Text(
                        "Barcha foydalanuvchilarga e'lon (Telegram)",
                        style: TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _broadcastCtrl,
                        minLines: 2,
                        maxLines: 5,
                        decoration: const InputDecoration(
                          hintText: "Xabar matnini yozing...",
                        ),
                      ),
                      const SizedBox(height: 12),
                      FilledButton.icon(
                        onPressed: _sendingBroadcast ? null : _sendBroadcast,
                        icon: _sendingBroadcast
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                              )
                            : const Icon(Icons.send_rounded),
                        label: const Text("Telegram orqali yuborish"),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              SectionHeader(
                title: "Audit Log",
                trailing: SpinningRefreshButton(onRefresh: _loadAudit),
              ),
              const SizedBox(height: 8),
              if (_loadingAudit)
                const Center(child: Padding(padding: EdgeInsets.all(20), child: CircularProgressIndicator()))
              else if (_auditLogs == null || _auditLogs!.isEmpty)
                const EmptyStateCard(icon: Icons.history_toggle_off, title: "Audit yozuvlari yo'q")
              else
                Card(
                  child: Column(
                    children: [
                      for (int i = 0; i < _auditLogs!.length; i++) ...[
                        if (i > 0) const Divider(),
                        ListTile(
                          dense: true,
                          title: Text(
                            asStr(_auditLogs![i]['action']),
                            style: const TextStyle(fontWeight: FontWeight.w700),
                          ),
                          subtitle: Text(
                            [
                              if (asStr(_auditLogs![i]['detail']).isNotEmpty)
                                asStr(_auditLogs![i]['detail']),
                              formatLocalDateTime(asStr(_auditLogs![i]['created_at'])),
                            ].join(" • "),
                          ),
                          trailing: Text(
                            "#${_auditLogs![i]['actor_id'] ?? _auditLogs![i]['actor_telegram_id'] ?? '-'}",
                            style: const TextStyle(fontSize: 11),
                          ),
                        ),
                      ],
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

class _TenantAdminCard extends StatelessWidget {
  const _TenantAdminCard({
    required this.tenant,
    required this.isActiveSelected,
    required this.onSwitch,
    required this.onManage,
  });

  final Map<String, dynamic> tenant;
  final bool isActiveSelected;
  final VoidCallback onSwitch;
  final VoidCallback onManage;

  @override
  Widget build(BuildContext context) {
    final id = asInt(tenant['id']);
    final name = asStr(tenant['tenant_name'] ?? tenant['name'], "Do'kon #$id");
    final status = asStr(tenant['status']);
    final isSuspended = tenant['is_suspended'] == true || status == 'suspended';
    final statusColor = isSuspended
        ? NorinPalette.danger
        : (status == 'active' ? NorinPalette.profit : NorinPalette.amber);
    final stats = asMap(tenant['stats']);
    final usersCount = asInt(tenant['users_count'] ?? stats['users']);
    final clientsCount = asInt(stats['clients']);
    final daysLeft = asInt(tenant['days_left']);

    return Card(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(18),
        side: BorderSide(
          color: isActiveSelected ? NorinPalette.indigo : Theme.of(context).dividerColor,
          width: isActiveSelected ? 1.8 : 1,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                CircleAvatar(
                  radius: 18,
                  backgroundColor: NorinPalette.indigo.withValues(alpha: 0.14),
                  child: Text(
                    '#$id',
                    style: const TextStyle(
                      color: NorinPalette.indigo,
                      fontWeight: FontWeight.w800,
                      fontSize: 13,
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(name, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15.5)),
                      Text(
                        "${asStr(tenant['plan_name'], 'Standard')} • ${formatUzs(asDouble(tenant['monthly_price']))}/oy",
                        style: const TextStyle(fontSize: 12),
                      ),
                    ],
                  ),
                ),
                StatusBadge(label: status, color: statusColor),
              ],
            ),
            const SizedBox(height: 10),
            Text(
              "$daysLeft kun • Xodim: $usersCount • Mijoz: $clientsCount • AI: ${asInt(tenant['ai_daily_limit']) == 0 ? 'Cheksiz' : tenant['ai_daily_limit']}",
              style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: onSwitch,
                    icon: Icon(
                      isActiveSelected ? Icons.check_circle_rounded : Icons.visibility_outlined,
                      size: 18,
                    ),
                    label: Text(isActiveSelected ? "Tanlangan" : "Ko'rish"),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton.tonalIcon(
                    onPressed: onManage,
                    icon: const Icon(Icons.settings_outlined, size: 18),
                    label: const Text("Boshqarish"),
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

class _TenantManageSheet extends ConsumerStatefulWidget {
  const _TenantManageSheet({required this.tenant, required this.onChanged});
  final Map<String, dynamic> tenant;
  final VoidCallback onChanged;

  @override
  ConsumerState<_TenantManageSheet> createState() => _TenantManageSheetState();
}

class _TenantManageSheetState extends ConsumerState<_TenantManageSheet> {
  late Map<String, dynamic> _t;
  List<Map<String, dynamic>>? _users;
  List<Map<String, dynamic>>? _payments;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _t = widget.tenant;
    _loadExtras();
  }

  int get _tid => asInt(_t['id']);

  Future<void> _loadExtras() async {
    final api = ref.read(apiClientProvider);
    try {
      final results = await Future.wait([
        api.get('/admin/tenants/$_tid/users'),
        api.get('/admin/tenants/$_tid/payments'),
      ]);
      if (mounted) {
        setState(() {
          _users = asMapList(results[0]);
          _payments = asMapList(results[1]);
        });
      }
    } catch (_) {}
  }

  Future<void> _extend(int days) async {
    final amountCtrl = TextEditingController(text: asDouble(_t['monthly_price']).round().toString());
    final noteCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text("Obunani +$days kun uzaytirish"),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: amountCtrl,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: "To'lov summasi (so'm)"),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: noteCtrl,
              decoration: const InputDecoration(labelText: "Izoh (Click / Naqd...)"),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Bekor")),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Uzaytirish")),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _busy = true);
    try {
      final updated = asMap(
        await ref.read(apiClientProvider).post(
          '/admin/tenants/$_tid/extend',
          data: {
            'days': days,
            'amount': double.tryParse(amountCtrl.text.trim()) ?? 0,
            'note': noteCtrl.text.trim(),
          },
        ),
      );
      setState(() => _t = {..._t, ...updated});
      widget.onChanged();
      await _loadExtras();
      if (mounted) showSnack(context, "+$days kun qo'shildi");
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _editMetaDialog() async {
    final nameCtrl = TextEditingController(text: asStr(_t['tenant_name'] ?? _t['name']));
    final planCtrl = TextEditingController(text: asStr(_t['plan_name'], 'Standard'));
    final priceCtrl = TextEditingController(text: asDouble(_t['monthly_price']).round().toString());
    final aiCtrl = TextEditingController(text: asInt(_t['ai_daily_limit']).toString());

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Do'kon sozlamalari"),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: nameCtrl, decoration: const InputDecoration(labelText: "Nomi")),
              const SizedBox(height: 10),
              TextField(controller: planCtrl, decoration: const InputDecoration(labelText: "Tarif")),
              const SizedBox(height: 10),
              TextField(
                controller: priceCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: "Oylik narx (so'm)"),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: aiCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: "Kunlik AI limit (0 = cheksiz)"),
              ),
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
    setState(() => _busy = true);
    try {
      final updated = asMap(
        await ref.read(apiClientProvider).patch(
          '/admin/tenants/$_tid',
          data: {
            'tenant_name': nameCtrl.text.trim(),
            'plan_name': planCtrl.text.trim(),
            'monthly_price': double.tryParse(priceCtrl.text.trim()) ?? 0,
            'ai_daily_limit': int.tryParse(aiCtrl.text.trim()) ?? 0,
          },
        ),
      );
      setState(() => _t = {..._t, ...updated});
      widget.onChanged();
      if (mounted) showSnack(context, "Sozlamalar saqlandi");
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _addUserDialog() async {
    final tgCtrl = TextEditingController();
    final nameCtrl = TextEditingController();
    String role = 'owner';

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          title: const Text("Foydalanuvchi qo'shish"),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: tgCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: "Telegram ID *"),
              ),
              const SizedBox(height: 10),
              TextField(controller: nameCtrl, decoration: const InputDecoration(labelText: "Ism")),
              const SizedBox(height: 10),
              DropdownButtonFormField<String>(
                key: ValueKey('role_$role'),
                initialValue: role,
                decoration: const InputDecoration(labelText: "Roli"),
                items: const [
                  DropdownMenuItem(value: 'owner', child: Text("Egasi (Owner)")),
                  DropdownMenuItem(value: 'staff', child: Text("Xodim (Staff)")),
                ],
                onChanged: (v) => setDlg(() => role = v ?? 'owner'),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text("Bekor")),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text("Qo'shish")),
          ],
        ),
      ),
    );
    if (ok != true) return;
    final tg = int.tryParse(tgCtrl.text.trim());
    if (tg == null || tg <= 0) {
      if (mounted) showSnack(context, "Telegram ID to'g'ri kiriting", error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(apiClientProvider).post(
        '/admin/users',
        data: {
          'telegram_id': tg,
          'full_name': nameCtrl.text.trim(),
          'role': role,
          'tenant_id': _tid,
        },
      );
      widget.onChanged();
      await _loadExtras();
      if (mounted) showSnack(context, "Foydalanuvchi qo'shildi");
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isSuspended = _t['is_suspended'] == true || asStr(_t['status']) == 'suspended';

    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.85,
      maxChildSize: 0.95,
      builder: (ctx, sc) => ListView(
        controller: sc,
        padding: EdgeInsets.fromLTRB(20, 4, 20, screenBottomClearance(ctx, extra: 24)),
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  "#$_tid ${asStr(_t['tenant_name'] ?? _t['name'])}",
                  style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800),
                ),
              ),
              IconButton(onPressed: _busy ? null : _editMetaDialog, icon: const Icon(Icons.edit_outlined)),
            ],
          ),
          Text(
            "${asStr(_t['plan_name'])} • ${asStr(_t['status'])} • ${asInt(_t['days_left'])} kun qoldi",
            style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 14),
          const Text("Obunani uzaytirish", style: TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: FilledButton.tonal(
                  onPressed: _busy ? null : () => _extend(7),
                  child: const Text("+7 kun"),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: FilledButton.tonal(
                  onPressed: _busy ? null : () => _extend(30),
                  child: const Text("+30 kun"),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: FilledButton.tonal(
                  onPressed: _busy ? null : () => _extend(90),
                  child: const Text("+90 kun"),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: _busy
                  ? null
                  : () async {
                      setState(() => _busy = true);
                      try {
                        final res = asMap(
                          await ref.read(apiClientProvider).post(
                            '/admin/tenants/$_tid/suspend',
                            data: {'is_suspended': !isSuspended},
                          ),
                        );
                        setState(() => _t = {..._t, ...res});
                        widget.onChanged();
                        if (context.mounted) {
                          showSnack(
                            context,
                            !isSuspended ? "Do'kon muzlatildi" : "Do'kon faollashtirildi",
                          );
                        }
                      } catch (e) {
                        if (context.mounted) showSnack(context, ApiClient.extractError(e), error: true);
                      } finally {
                        if (mounted) setState(() => _busy = false);
                      }
                    },
              icon: Icon(isSuspended ? Icons.play_arrow_rounded : Icons.pause_rounded),
              label: Text(isSuspended ? "Faollashtirish" : "Muzlatish"),
            ),
          ),
          const SizedBox(height: 16),
          SectionHeader(
            title: "Foydalanuvchilar (${_users?.length ?? 0})",
            trailing: TextButton.icon(
              onPressed: _busy ? null : _addUserDialog,
              icon: const Icon(Icons.person_add_alt_1_rounded, size: 18),
              label: const Text("Qo'shish"),
            ),
          ),
          const SizedBox(height: 6),
          if (_users == null)
            const LinearProgressIndicator()
          else if (_users!.isEmpty)
            const Text("Foydalanuvchilar yo'q")
          else
            Card(
              child: Column(
                children: [
                  for (int i = 0; i < _users!.length; i++) ...[
                    if (i > 0) const Divider(),
                    ListTile(
                      dense: true,
                      title: Text(
                        asStr(_users![i]['full_name']).trim().isNotEmpty
                            ? asStr(_users![i]['full_name'])
                            : "ID ${_users![i]['telegram_id']}",
                        style: const TextStyle(fontWeight: FontWeight.w700),
                      ),
                      subtitle: Text("ID: ${_users![i]['telegram_id']} • ${asStr(_users![i]['role'])}"),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          IconButton(
                            tooltip: "Rolni almashtirish",
                            icon: const Icon(Icons.swap_horiz_rounded, size: 20),
                            onPressed: _busy
                                ? null
                                : () async {
                                    final curRole = asStr(_users![i]['role'], 'staff');
                                    final nextRole = curRole == 'owner' ? 'staff' : 'owner';
                                    try {
                                      await ref.read(apiClientProvider).patch(
                                        '/admin/users/${asInt(_users![i]['telegram_id'])}',
                                        data: {'role': nextRole},
                                      );
                                      widget.onChanged();
                                      await _loadExtras();
                                      if (context.mounted) showSnack(context, "Roli: $nextRole");
                                    } catch (e) {
                                      if (context.mounted) {
                                        showSnack(context, ApiClient.extractError(e), error: true);
                                      }
                                    }
                                  },
                          ),
                          IconButton(
                            tooltip: "O'chirish",
                            icon: const Icon(Icons.delete_outline, color: NorinPalette.danger, size: 20),
                            onPressed: _busy
                                ? null
                                : () async {
                                    final tgId = asInt(_users![i]['telegram_id']);
                                    final yes = await showConfirmDialog(
                                      context,
                                      title: "Foydalanuvchini uzish",
                                      message: "ID $tgId ruxsati bekor qilinsinmi?",
                                      confirmLabel: "O'chirish",
                                      destructive: true,
                                    );
                                    if (!yes) return;
                                    try {
                                      await ref.read(apiClientProvider).delete('/admin/users/$tgId');
                                      widget.onChanged();
                                      await _loadExtras();
                                      if (context.mounted) showSnack(context, "Foydalanuvchi o'chirildi");
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
                  ],
                ],
              ),
            ),
          const SizedBox(height: 16),
          Text("To'lovlar tarixi (${_payments?.length ?? 0})", style: const TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          if (_payments != null && _payments!.isNotEmpty)
            Card(
              child: Column(
                children: [
                  for (int i = 0; i < _payments!.length; i++) ...[
                    if (i > 0) const Divider(),
                    ListTile(
                      dense: true,
                      title: Text(formatUzs(asDouble(_payments![i]['amount'])), style: const TextStyle(fontWeight: FontWeight.w700)),
                      subtitle: Text("+${asInt(_payments![i]['days_added'])} kun • ${asStr(_payments![i]['note'])}"),
                      trailing: Text(
                        formatShortDate(asStr(_payments![i]['paid_at'] ?? _payments![i]['created_at'])),
                      ),
                    ),
                  ],
                ],
              ),
            )
          else
            const Text("To'lovlar tarixi bo'sh"),
          const SizedBox(height: 18),
          const Text("Xavfli hudud", style: TextStyle(color: NorinPalette.danger, fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _busy
                      ? null
                      : () async {
                          final yes = await showConfirmDialog(
                            context,
                            title: "Savdolarni tozalash",
                            message: "Do'kon #$_tid dagi barcha sotuv va kassa yozuvlari o'chirilsinmi?",
                            confirmLabel: "Tozalash",
                            destructive: true,
                          );
                          if (!yes) return;
                          setState(() => _busy = true);
                          try {
                            await ref
                                .read(apiClientProvider)
                                .post('/admin/tenants/$_tid/clear', data: {'mode': 'tx'});
                            widget.onChanged();
                            if (ref.read(authProvider).selectedTenantId == _tid) {
                              invalidateOperationalData(ref);
                            }
                            if (context.mounted) showSnack(context, "Savdolar tozalandi");
                          } catch (e) {
                            if (context.mounted) showSnack(context, ApiClient.extractError(e), error: true);
                          } finally {
                            if (mounted) setState(() => _busy = false);
                          }
                        },
                  child: const Text("Savdolarni tozalash"),
                ),
              ),
              if (_tid > 1) ...[
                const SizedBox(width: 10),
                Expanded(
                  child: FilledButton(
                    style: FilledButton.styleFrom(backgroundColor: NorinPalette.danger),
                    onPressed: _busy
                        ? null
                        : () async {
                            final yes = await showConfirmDialog(
                              context,
                              title: "Do'konni o'chirish",
                              message: "Do'kon #$_tid butunlay o'chirilsinmi?",
                              confirmLabel: "O'chirish",
                              destructive: true,
                            );
                            if (!yes) return;
                            setState(() => _busy = true);
                            try {
                              if (ref.read(authProvider).selectedTenantId == _tid) {
                                await ref.read(authProvider.notifier).selectTenant(1);
                                invalidateOperationalData(ref);
                              }
                              await ref.read(apiClientProvider).delete('/admin/tenants/$_tid');
                              widget.onChanged();
                              if (ctx.mounted) Navigator.pop(ctx);
                              if (context.mounted) showSnack(context, "Do'kon o'chirildi");
                            } catch (e) {
                              if (context.mounted) showSnack(context, ApiClient.extractError(e), error: true);
                            } finally {
                              if (mounted) setState(() => _busy = false);
                            }
                          },
                    child: const Text("Do'konni o'chirish"),
                  ),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }
}
