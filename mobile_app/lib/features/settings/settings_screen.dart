import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/security/biometric_lock.dart';
import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/update/app_updater.dart';
import '../../core/utils/formatters.dart';
import '../../core/version.dart';
import '../../core/widgets/metric_cards.dart';
import '../../core/widgets/norin_widgets.dart';
import '../admin/admin_screen.dart';

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  Future<void> _productDialog(
    BuildContext context,
    WidgetRef ref, {
    Map<String, dynamic>? existing,
  }) async {
    final isEdit = existing != null;
    final nameCtrl = TextEditingController(text: asStr(existing?['name']));
    final costCtrl = TextEditingController(
      text: existing != null ? asDouble(existing['cost_price']).round().toString() : '',
    );
    final sellCtrl = TextEditingController(
      text: existing != null ? asDouble(existing['default_sell_price']).round().toString() : '',
    );
    final aliasCtrl = TextEditingController(text: asStr(existing?['aliases']));
    String unit = asStr(existing?['unit'], 'kg');
    if (!const ['kg', 'dona', 'porsiya', 'litr'].contains(unit)) unit = 'kg';

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDlg) => AlertDialog(
          title: Text(isEdit ? "Mahsulotni tahrirlash" : "Yangi mahsulot"),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(controller: nameCtrl, decoration: const InputDecoration(labelText: "Nomi *")),
                const SizedBox(height: 10),
                TextField(
                  controller: costCtrl,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: "Tannarxi (so'm) *"),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: sellCtrl,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: "Sotuv narxi (so'm) *"),
                ),
                const SizedBox(height: 10),
                DropdownButtonFormField<String>(
                  key: ValueKey('unit_$unit'),
                  initialValue: unit,
                  decoration: const InputDecoration(labelText: "Birlik"),
                  items: const [
                    DropdownMenuItem(value: 'kg', child: Text("kg")),
                    DropdownMenuItem(value: 'dona', child: Text("dona")),
                    DropdownMenuItem(value: 'porsiya', child: Text("porsiya")),
                    DropdownMenuItem(value: 'litr', child: Text("litr")),
                  ],
                  onChanged: (v) => setDlg(() => unit = v ?? 'kg'),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: aliasCtrl,
                  decoration: const InputDecoration(labelText: "Aliases (vergul bilan)"),
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
    final name = nameCtrl.text.trim();
    final cost = double.tryParse(costCtrl.text.trim()) ?? -1;
    final sell = double.tryParse(sellCtrl.text.trim()) ?? -1;
    if (name.isEmpty || cost < 0 || sell <= 0) {
      if (context.mounted) showSnack(context, "Maydonlarni to'g'ri to'ldiring", error: true);
      return;
    }
    try {
      final api = ref.read(apiClientProvider);
      final body = {
        'name': name,
        'cost_price': cost,
        'default_sell_price': sell,
        'unit': unit,
        'aliases': aliasCtrl.text.trim(),
      };
      if (isEdit) {
        await api.patch('/products/${asInt(existing['id'])}', data: body);
      } else {
        await api.post('/products', data: body);
      }
      invalidateOperationalData(ref);
      if (context.mounted) showSnack(context, isEdit ? "Mahsulot yangilandi" : "Mahsulot qo'shildi");
    } catch (e) {
      if (context.mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  }

  Future<void> _showDevicesSheet(BuildContext context, WidgetRef ref) async {
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (ctx) => _DevicesSheet(api: ref.read(apiClientProvider)),
    );
  }

  Future<void> _patchSetting(
    BuildContext context,
    WidgetRef ref,
    Map<String, dynamic> patch,
  ) async {
    try {
      await ref.read(apiClientProvider).patch('/settings', data: patch);
      ref.invalidate(settingsProvider);
      if (context.mounted) showSnack(context, "Sozlama saqlandi");
    } catch (e) {
      if (context.mounted) showSnack(context, ApiClient.extractError(e), error: true);
    }
  }

  Future<void> _pinDialog(BuildContext context, WidgetRef ref, BiometricLockState bioLock) async {
    final pinCtrl = TextEditingController();
    final action = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("4 xonali PIN-kod"),
        content: TextField(
          controller: pinCtrl,
          keyboardType: TextInputType.number,
          maxLength: 4,
          obscureText: true,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          decoration: const InputDecoration(
            labelText: "Yangi 4 xonali PIN",
            hintText: "••••",
            counterText: "",
          ),
        ),
        actions: [
          if (bioLock.hasPin)
            TextButton(
              onPressed: () => Navigator.pop(ctx, 'clear'),
              child: const Text("O'chirish", style: TextStyle(color: NorinPalette.danger)),
            ),
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text("Bekor")),
          FilledButton(onPressed: () => Navigator.pop(ctx, 'save'), child: const Text("Saqlash")),
        ],
      ),
    );
    if (action == 'clear') {
      await ref.read(biometricLockProvider.notifier).setPinCode(null);
      if (context.mounted) showSnack(context, "PIN-kod o'chirildi");
      return;
    }
    if (action == 'save') {
      final p = pinCtrl.text.trim();
      if (p.length != 4) {
        if (context.mounted) showSnack(context, "4 ta raqam kiriting", error: true);
        return;
      }
      await ref.read(biometricLockProvider.notifier).setPinCode(p);
      if (context.mounted) showSnack(context, "PIN-kod saqlandi");
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    final isAdmin = auth.isSuperAdmin;
    final settingsAsync = ref.watch(settingsProvider);
    final productsAsync = ref.watch(productsProvider);
    final bioLock = ref.watch(biometricLockProvider);
    final themeMode = ref.watch(themeModeProvider);
    final api = ref.read(apiClientProvider);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: AppBar(
        title: const Text("Sozlamalar", style: TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          SpinningRefreshButton(
            onRefresh: () async {
              ref.invalidate(settingsProvider);
              ref.invalidate(productsProvider);
              if (isAdmin) {
                ref.invalidate(adminTenantsProvider);
                ref.invalidate(adminAnalyticsProvider);
              }
              await ref.read(settingsProvider.future).catchError((_) => <String, dynamic>{});
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 120),
        children: [
          if (isAdmin) ...[
            _SuperAdminSettingsCard(selectedTenantId: auth.selectedTenantId),
            const SizedBox(height: 16),
          ],
          settingsAsync.when(
            loading: () => const Card(
              child: Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator())),
            ),
            error: (e, _) => AsyncErrorCard(
              error: e,
              onRetry: () => ref.invalidate(settingsProvider),
            ),
            data: (se) {
              final tenant = asMap(se['tenant']);
              final sub = asMap(se['subscription']);
              final ai = asMap(se['ai']);
              final rep = se['report_group'] == null ? null : asMap(se['report_group']);
              final roundMode = asStr(se['round_mode'], 'none');
              final status = asStr(sub['status']);
              final daysLeft = asInt(sub['days_left']);
              final aiLimit = asInt(ai['daily_limit']);
              final aiUsed = asInt(ai['used_today']);

              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SpotlightHeroCard(
                    padding: const EdgeInsets.all(18),
                    borderRadius: 20,
                    glowColor: NorinPalette.emeraldLight,
                    accentColor: NorinPalette.indigo,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                asStr(tenant['name'], "Do'konim"),
                                style: const TextStyle(
                                  fontSize: 18,
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                            ),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                              decoration: BoxDecoration(
                                color: NorinPalette.emerald.withValues(alpha: 0.16),
                                borderRadius: BorderRadius.circular(999),
                              ),
                              child: Text(
                                "${asStr(sub['plan'], 'Standard')} • $status",
                                style: const TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(
                          "$daysLeft kun • AI: ${aiLimit == 0 ? 'Cheksiz' : '$aiUsed/$aiLimit'}",
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.onSurfaceVariant,
                            fontSize: 12.5,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  const SectionHeader(title: "Avtomatizatsiya"),
                  const SizedBox(height: 8),
                  Card(
                    child: Column(
                      children: [
                        SwitchListTile(
                          title: const Text("Avto-tasdiq", style: TextStyle(fontWeight: FontWeight.w600)),
                          subtitle: const Text("Chekni darhol saqlash"),
                          value: se['auto_confirm'] == true,
                          onChanged: (v) => _patchSetting(context, ref, {'auto_confirm': v}),
                        ),
                        const Divider(),
                        SwitchListTile(
                          title: const Text("Guruh avto-hisob", style: TextStyle(fontWeight: FontWeight.w600)),
                          subtitle: const Text("Guruh rasmlarini hisoblash"),
                          value: se['group_auto_calc'] == true,
                          onChanged: (v) => _patchSetting(context, ref, {'group_auto_calc': v}),
                        ),
                        const Divider(),
                        Padding(
                          padding: const EdgeInsets.all(14),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text("Yaxlitlash", style: TextStyle(fontWeight: FontWeight.w600)),
                              const SizedBox(height: 8),
                              SizedBox(
                                width: double.infinity,
                                child: SegmentedButton<String>(
                                  showSelectedIcon: false,
                                  segments: const [
                                    ButtonSegment(value: 'none', label: Text("Yo'q")),
                                    ButtonSegment(value: 'nearest_1000', label: Text("1000")),
                                    ButtonSegment(value: 'floor_1000', label: Text("Pastga")),
                                  ],
                                  selected: {roundMode},
                                  onSelectionChanged: (s) =>
                                      _patchSetting(context, ref, {'round_mode': s.first}),
                                ),
                              ),
                            ],
                          ),
                        ),
                        if (rep != null) ...[
                          const Divider(),
                          ListTile(
                            leading: const Icon(Icons.groups_2_outlined),
                            title: const Text("Hisobot guruhi"),
                            subtitle: Text(asStr(rep['title'])),
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
          SectionHeader(
            title: "Mahsulotlar",
            trailing: FilledButton.tonalIcon(
              onPressed: () => _productDialog(context, ref),
              icon: const Icon(Icons.add, size: 18),
              label: const Text("Qo'shish"),
            ),
          ),
          const SizedBox(height: 8),
          productsAsync.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (e, _) => AsyncErrorCard(
              error: e,
              onRetry: () => ref.invalidate(productsProvider),
            ),
            data: (products) => products.isEmpty
                ? const EmptyStateCard(icon: Icons.inventory_2_outlined, title: "Mahsulotlar yo'q")
                : Card(
                    child: Column(
                      children: [
                        for (int i = 0; i < products.length; i++) ...[
                          if (i > 0) const Divider(),
                          ListTile(
                            onTap: () => _productDialog(context, ref, existing: products[i]),
                            title: Text(
                              "${asStr(products[i]['name'])} (${asStr(products[i]['unit'], 'kg')})",
                              style: const TextStyle(fontWeight: FontWeight.w700),
                            ),
                            subtitle: Text(
                              "${formatUzs(asDouble(products[i]['cost_price']))} → ${formatUzs(asDouble(products[i]['default_sell_price']))}",
                            ),
                            trailing: IconButton(
                              icon: const Icon(Icons.delete_outline, color: NorinPalette.danger),
                              onPressed: () async {
                                final yes = await showConfirmDialog(
                                  context,
                                  title: "Mahsulotni o'chirish",
                                  message: "\"${asStr(products[i]['name'])}\" o'chirilsinmi?",
                                  destructive: true,
                                );
                                if (!yes) return;
                                await api.delete('/products/${asInt(products[i]['id'])}');
                                invalidateOperationalData(ref);
                              },
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
          ),
          const SizedBox(height: 18),
          const SectionHeader(title: "Ilova va xavfsizlik"),
          const SizedBox(height: 8),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.palette_outlined),
                  title: const Text("Mavzu"),
                  trailing: DropdownButton<ThemeMode>(
                    value: themeMode,
                    underline: const SizedBox.shrink(),
                    items: const [
                      DropdownMenuItem(value: ThemeMode.system, child: Text("Tizim")),
                      DropdownMenuItem(value: ThemeMode.light, child: Text("Oq")),
                      DropdownMenuItem(value: ThemeMode.dark, child: Text("Qora")),
                    ],
                    onChanged: (m) {
                      if (m != null) ref.read(themeModeProvider.notifier).state = m;
                    },
                  ),
                ),
                const Divider(),
                SwitchListTile(
                  secondary: const Icon(Icons.fingerprint_rounded, color: NorinPalette.emeraldLight),
                  title: const Text("Barmoq izi"),
                  subtitle: Text(
                    bioLock.enabled
                        ? "Yoqilgan"
                        : (bioLock.biometricAvailable ? "O'chirilgan" : "Mavjud emas"),
                  ),
                  value: bioLock.enabled,
                  onChanged: (v) async {
                    final ok = await ref
                        .read(biometricLockProvider.notifier)
                        .setBiometricEnabled(v);
                    if (!context.mounted) return;
                    if (v) {
                      showSnack(
                        context,
                        ok
                            ? "Barmoq izi yoqildi"
                            : "Tasdiqlanmadi yoki sozlanmagan",
                        error: !ok,
                      );
                    } else {
                      showSnack(context, "Barmoq izi o'chirildi");
                    }
                  },
                ),
                const Divider(),
                ListTile(
                  leading: const Icon(Icons.pin_outlined),
                  title: const Text("PIN-kod"),
                  subtitle: Text(bioLock.hasPin ? "O'rnatilgan" : "O'rnatilmagan"),
                  trailing: const Icon(Icons.chevron_right_rounded),
                  onTap: () => _pinDialog(context, ref, bioLock),
                ),
                const Divider(),
                ListTile(
                  leading: const Icon(Icons.system_update_rounded, color: NorinPalette.emerald),
                  title: const Text("Yangilash"),
                  subtitle: Text("v$kAppVersion (#$kAppBuildNumber)"),
                  trailing: const Icon(Icons.chevron_right_rounded),
                  onTap: () => checkAndPromptUpdate(context, api, silentIfLatest: false),
                ),
                const Divider(),
                ListTile(
                  leading: const Icon(Icons.devices_rounded),
                  title: const Text("Qurilmalar"),
                  trailing: const Icon(Icons.chevron_right_rounded),
                  onTap: () => _showDevicesSheet(context, ref),
                ),
                const Divider(),
                ListTile(
                  leading: const Icon(Icons.logout_rounded, color: NorinPalette.danger),
                  title: const Text(
                    "Chiqish",
                    style: TextStyle(color: NorinPalette.danger, fontWeight: FontWeight.w700),
                  ),
                  onTap: () async {
                    final yes = await showConfirmDialog(
                      context,
                      title: "Chiqish",
                      message: "Hisobdan chiqasizmi?",
                      confirmLabel: "Chiqish",
                      destructive: true,
                    );
                    if (yes) {
                      ref.read(biometricLockProvider.notifier).resetSessionLock();
                      await ref.read(authProvider.notifier).logout();
                    }
                  },
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _DevicesSheet extends StatefulWidget {
  const _DevicesSheet({required this.api});
  final ApiClient api;

  @override
  State<_DevicesSheet> createState() => _DevicesSheetState();
}

class _DevicesSheetState extends State<_DevicesSheet> {
  late Future<List<Map<String, dynamic>>> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    _future = widget.api.get('/auth/devices').then((d) => asMapList(d));
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<Map<String, dynamic>>>(
      future: _future,
      builder: (ctx, snap) {
        if (snap.connectionState == ConnectionState.waiting) {
          return const SizedBox(height: 180, child: Center(child: CircularProgressIndicator()));
        }
        if (snap.hasError) {
          return AsyncErrorCard(error: snap.error!, onRetry: () => setState(_load));
        }
        final devs = snap.data ?? const [];
        return ListView.separated(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 24),
          itemCount: devs.length + 1,
          separatorBuilder: (_, _) => const SizedBox(height: 6),
          itemBuilder: (ctx, i) {
            if (i == 0) {
              return const Text(
                "Faol APK Qurilmalari",
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
              );
            }
            final d = devs[i - 1];
            return ListTile(
              leading: const Icon(Icons.phone_android_rounded),
              title: Text(asStr(d['device_name'], 'Android')),
              subtitle: Text("Yaratilgan: ${formatLocalDateTime(asStr(d['created_at']))}"),
              trailing: IconButton(
                icon: const Icon(Icons.delete_outline, color: NorinPalette.danger),
                onPressed: () async {
                  await widget.api.delete('/auth/devices/${asInt(d['id'])}');
                  setState(_load);
                },
              ),
            );
          },
        );
      },
    );
  }
}

class _SuperAdminSettingsCard extends ConsumerWidget {
  const _SuperAdminSettingsCard({required this.selectedTenantId});

  final int selectedTenantId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tenantsAsync = ref.watch(adminTenantsProvider);
    final tenants = tenantsAsync.valueOrNull ?? const <Map<String, dynamic>>[];

    return SpotlightHeroCard(
      padding: const EdgeInsets.all(16),
      borderRadius: 20,
      glowColor: NorinPalette.magenta,
      accentColor: NorinPalette.indigo,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: NorinPalette.magenta.withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Icon(
                  Icons.admin_panel_settings_rounded,
                  color: NorinPalette.emerald,
                  size: 20,
                ),
              ),
              const SizedBox(width: 10),
              const Expanded(
                child: Text(
                  "Admin boshqaruvi",
                  style: TextStyle(
                    fontSize: 15.5,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ),
            ],
          ),
          if (tenants.isNotEmpty) ...[
            const SizedBox(height: 12),
            SizedBox(
              height: 36,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: tenants.length,
                separatorBuilder: (_, _) => const SizedBox(width: 8),
                itemBuilder: (ctx, i) {
                  final t = tenants[i];
                  final tid = asInt(t['id']);
                  final tName = asStr(t['tenant_name'] ?? t['name'], 'Do\'kon #$tid');
                  final active = tid == selectedTenantId;
                  return ChoiceChip(
                    selected: active,
                    label: Text(
                      tName,
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: active ? FontWeight.w800 : FontWeight.w600,
                      ),
                    ),
                    onSelected: (_) async {
                      await ref.read(authProvider.notifier).selectTenant(tid);
                      invalidateOperationalData(ref);
                      if (context.mounted) {
                        showSnack(context, "Tanlandi: $tName");
                      }
                    },
                  );
                },
              ),
            ),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: () {
                    Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const AdminScreen(initialTab: 0)),
                    );
                  },
                  icon: const Icon(Icons.insights_rounded, size: 18),
                  label: const Text("Statistika"),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: FilledButton.tonalIcon(
                  onPressed: () {
                    Navigator.of(context).push(
                      MaterialPageRoute(builder: (_) => const AdminScreen(initialTab: 1)),
                    );
                  },
                  icon: const Icon(Icons.store_mall_directory_rounded, size: 18),
                  label: const Text("Do'konlar"),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
