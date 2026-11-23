import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/update/app_updater.dart';
import '../admin/admin_screen.dart';
import '../cash/cash_screen.dart';
import '../clients/clients_screen.dart';
import '../dashboard/dashboard_screen.dart';
import '../sales/sale_sheets.dart';
import '../settings/settings_screen.dart';

final shellTabIndexProvider = StateProvider<int>((ref) => 0);

class MainShell extends ConsumerStatefulWidget {
  const MainShell({super.key});

  @override
  ConsumerState<MainShell> createState() => _MainShellState();
}

class _MainShellState extends ConsumerState<MainShell> {
  bool _checkedUpdate = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_checkedUpdate || !mounted) return;
      _checkedUpdate = true;
      checkAndPromptUpdate(context, ref.read(apiClientProvider), silentIfLatest: true);
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final isAdmin = auth.isSuperAdmin;
    final rawIdx = ref.watch(shellTabIndexProvider);

    final pages = <Widget>[
      const DashboardScreen(),
      const ClientsScreen(),
      const CashScreen(),
      if (isAdmin) const AdminScreen(),
      const SettingsScreen(),
    ];

    final destinations = <NavigationDestination>[
      const NavigationDestination(
        icon: Icon(Icons.dashboard_outlined),
        selectedIcon: Icon(Icons.dashboard_rounded),
        label: "Boshqaruv",
      ),
      const NavigationDestination(
        icon: Icon(Icons.people_outline_rounded),
        selectedIcon: Icon(Icons.people_rounded),
        label: "Mijozlar",
      ),
      const NavigationDestination(
        icon: Icon(Icons.account_balance_wallet_outlined),
        selectedIcon: Icon(Icons.account_balance_wallet_rounded),
        label: "Kassa",
      ),
      if (isAdmin)
        const NavigationDestination(
          icon: Icon(Icons.admin_panel_settings_outlined),
          selectedIcon: Icon(Icons.admin_panel_settings_rounded, color: NorinPalette.indigo),
          label: "Admin",
        ),
      const NavigationDestination(
        icon: Icon(Icons.tune_outlined),
        selectedIcon: Icon(Icons.tune_rounded),
        label: "Sozlama",
      ),
    ];

    final idx = rawIdx >= pages.length ? 0 : rawIdx;
    final showSaleFab = idx <= 2;

    return Scaffold(
      body: IndexedStack(index: idx, children: pages),
      floatingActionButton: showSaleFab
          ? FloatingActionButton.extended(
              onPressed: () => openNewSaleSheet(context, ref),
              icon: const Icon(Icons.auto_awesome_rounded),
              label: const Text(
                "Sotuv / AI",
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
            )
          : null,
      bottomNavigationBar: NavigationBar(
        selectedIndex: idx,
        onDestinationSelected: (v) => ref.read(shellTabIndexProvider.notifier).state = v,
        destinations: destinations,
      ),
    );
  }
}
