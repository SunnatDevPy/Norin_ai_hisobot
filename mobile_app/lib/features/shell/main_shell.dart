import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/update/app_updater.dart';
import '../../core/widgets/metric_cards.dart';
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
    final rawIdx = ref.watch(shellTabIndexProvider);

    const pages = <Widget>[
      DashboardScreen(),
      ClientsScreen(),
      CashScreen(),
      SettingsScreen(),
    ];

    const navItems = <({IconData icon, IconData activeIcon, String label})>[
      (icon: Icons.home_outlined, activeIcon: Icons.home_rounded, label: "Asosiy"),
      (icon: Icons.people_outline_rounded, activeIcon: Icons.people_rounded, label: "Mijozlar"),
      (
        icon: Icons.account_balance_wallet_outlined,
        activeIcon: Icons.account_balance_wallet_rounded,
        label: "Kassa"
      ),
      (icon: Icons.tune_outlined, activeIcon: Icons.tune_rounded, label: "Sozlamalar"),
    ];

    final idx = rawIdx >= pages.length ? 0 : rawIdx;

    return Scaffold(
      extendBody: true,
      backgroundColor: Colors.transparent,
      body: CosmicBackground(
        child: IndexedStack(index: idx, children: pages),
      ),
      bottomNavigationBar: _FloatingGlassDock(
        items: navItems,
        selectedIndex: idx,
        onTap: (v) => ref.read(shellTabIndexProvider.notifier).state = v,
        onCenterAiTap: () => openNewSaleSheet(context, ref),
      ),
    );
  }
}

class _FloatingGlassDock extends StatelessWidget {
  const _FloatingGlassDock({
    required this.items,
    required this.selectedIndex,
    required this.onTap,
    required this.onCenterAiTap,
  });

  final List<({IconData icon, IconData activeIcon, String label})> items;
  final int selectedIndex;
  final ValueChanged<int> onTap;
  final VoidCallback onCenterAiTap;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
        child: SizedBox(
          height: 76,
          child: Stack(
            clipBehavior: Clip.none,
            alignment: Alignment.bottomCenter,
            children: [
              Container(
                height: 64,
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
                decoration: BoxDecoration(
                  color: isDark ? const Color(0xF2151421) : const Color(0xF5FFFFFF),
                  borderRadius: BorderRadius.circular(24),
                  border: Border.all(
                    color: isDark ? const Color(0xFF312C4A) : NorinPalette.lightBorder,
                    width: 1,
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: (isDark ? Colors.black : NorinPalette.emeraldDark)
                          .withValues(alpha: 0.35),
                      blurRadius: 24,
                      offset: const Offset(0, 10),
                    ),
                  ],
                ),
                child: Row(
                  children: [
                    for (int i = 0; i < 2; i++)
                      Expanded(
                        child: _DockButton(
                          icon: items[i].icon,
                          activeIcon: items[i].activeIcon,
                          label: items[i].label,
                          selected: i == selectedIndex,
                          onTap: () => onTap(i),
                        ),
                      ),
                    const SizedBox(width: 72),
                    for (int i = 2; i < items.length; i++)
                      Expanded(
                        child: _DockButton(
                          icon: items[i].icon,
                          activeIcon: items[i].activeIcon,
                          label: items[i].label,
                          selected: i == selectedIndex,
                          onTap: () => onTap(i),
                        ),
                      ),
                  ],
                ),
              ),
              Positioned(
                top: 0,
                child: _CenterCircularAiButton(onTap: onCenterAiTap),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CenterCircularAiButton extends StatelessWidget {
  const _CenterCircularAiButton({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 62,
        height: 62,
        padding: const EdgeInsets.all(3.5),
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: isDark ? const Color(0xFF151421) : Colors.white,
          border: Border.all(
            color: NorinPalette.magenta.withValues(alpha: 0.55),
            width: 1.4,
          ),
          boxShadow: [
            BoxShadow(
              color: NorinPalette.emerald.withValues(alpha: 0.55),
              blurRadius: 20,
              spreadRadius: 1,
              offset: const Offset(0, 5),
            ),
          ],
        ),
        child: Container(
          decoration: const BoxDecoration(
            shape: BoxShape.circle,
            gradient: NorinPalette.neonPurpleGradient,
          ),
          child: const Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                Icons.auto_awesome_rounded,
                size: 23,
                color: Color(0xFF1A0B2E),
              ),
              Text(
                "AI",
                style: TextStyle(
                  fontSize: 9.5,
                  height: 1.05,
                  fontWeight: FontWeight.w900,
                  color: Color(0xFF1A0B2E),
                  letterSpacing: 0.4,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DockButton extends StatelessWidget {
  const _DockButton({
    required this.icon,
    required this.activeIcon,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final IconData icon;
  final IconData activeIcon;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final activeCol = isDark ? NorinPalette.emeraldLight : NorinPalette.emeraldDark;
    final mutedCol = isDark ? NorinPalette.darkMuted : NorinPalette.lightMuted;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(18),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOutCubic,
        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(18),
          gradient: selected
              ? LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [
                    NorinPalette.emerald.withValues(alpha: isDark ? 0.28 : 0.16),
                    NorinPalette.indigo.withValues(alpha: isDark ? 0.10 : 0.05),
                  ],
                )
              : null,
          border: selected
              ? Border.all(color: activeCol.withValues(alpha: 0.45), width: 1)
              : null,
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              selected ? activeIcon : icon,
              size: 20,
              color: selected ? activeCol : mutedCol,
            ),
            const SizedBox(height: 2),
            Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                fontSize: 10,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                color: selected ? (isDark ? Colors.white : activeCol) : mutedCol,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
