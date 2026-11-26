import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/security/biometric_lock.dart';
import 'core/state/providers.dart';
import 'core/theme/app_theme.dart';
import 'core/widgets/metric_cards.dart';
import 'features/auth/login_screen.dart';
import 'features/shell/main_shell.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      systemNavigationBarColor: Colors.transparent,
      systemNavigationBarDividerColor: Colors.transparent,
      systemNavigationBarContrastEnforced: false,
    ),
  );
  runApp(const ProviderScope(child: NorinAiApp()));
}

class NorinAiApp extends ConsumerStatefulWidget {
  const NorinAiApp({super.key});

  @override
  ConsumerState<NorinAiApp> createState() => _NorinAiAppState();
}

class _NorinAiAppState extends ConsumerState<NorinAiApp> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    Future.microtask(() async {
      await ref.read(themeModeProvider.notifier).init();
      await ref.read(biometricLockProvider.notifier).init();
      await ref.read(authProvider.notifier).bootstrap();
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final notifier = ref.read(biometricLockProvider.notifier);
    if (state == AppLifecycleState.paused || state == AppLifecycleState.hidden) {
      notifier.onAppPaused();
    } else if (state == AppLifecycleState.resumed) {
      notifier.onAppResumed();
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final bioLock = ref.watch(biometricLockProvider);
    final themeMode = ref.watch(themeModeProvider);

    final String stageKey;
    final Widget home;
    if (auth.stage == AuthStage.loading || !bioLock.initialized) {
      stageKey = 'splash';
      home = const _SplashView();
    } else if (auth.stage == AuthStage.unauthenticated) {
      stageKey = 'login';
      home = const LoginScreen();
    } else if (bioLock.locked) {
      stageKey = 'lock';
      home = const BiometricLockScreen();
    } else if (!bioLock.setupCompleted && !bioLock.hasAnyLock) {
      stageKey = 'pin_setup';
      home = const PinSetupScreen();
    } else {
      stageKey = 'main';
      home = const MainShell();
    }

    return MaterialApp(
      title: 'Sotuv AI',
      debugShowCheckedModeBanner: false,
      themeMode: themeMode,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      builder: (context, child) {
        final isDark = Theme.of(context).brightness == Brightness.dark;
        return AnnotatedRegion<SystemUiOverlayStyle>(
          value: SystemUiOverlayStyle(
            statusBarColor: Colors.transparent,
            statusBarIconBrightness: isDark ? Brightness.light : Brightness.dark,
            systemNavigationBarColor: Colors.transparent,
            systemNavigationBarDividerColor: Colors.transparent,
            systemNavigationBarIconBrightness: isDark ? Brightness.light : Brightness.dark,
            systemNavigationBarContrastEnforced: false,
          ),
          child: child ?? const SizedBox.shrink(),
        );
      },
      home: AnimatedSwitcher(
        duration: const Duration(milliseconds: 340),
        switchInCurve: Curves.easeOutCubic,
        switchOutCurve: Curves.easeIn,
        transitionBuilder: (child, anim) => FadeTransition(
          opacity: anim,
          child: ScaleTransition(
            scale: Tween<double>(begin: 0.96, end: 1.0).animate(anim),
            child: child,
          ),
        ),
        child: KeyedSubtree(key: ValueKey(stageKey), child: home),
      ),
    );
  }
}

class _SplashView extends StatelessWidget {
  const _SplashView();

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Scaffold(
      body: CosmicBackground(
        showBottomHorizonGlow: true,
        child: Center(
          child: TweenAnimationBuilder<double>(
            tween: Tween(begin: 0.88, end: 1.0),
            duration: const Duration(milliseconds: 520),
            curve: Curves.easeOutBack,
            builder: (_, scale, child) => Transform.scale(scale: scale, child: child),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const GlowingSquircleEmblem(size: 102),
                const SizedBox(height: 12),
                const Text(
                  "Sotuv AI",
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.w900, letterSpacing: -0.4),
                ),
                const SizedBox(height: 4),
                Text(
                  "Savdo, qarz va kassa",
                  style: TextStyle(
                    fontSize: 12.5,
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: 22),
                SizedBox(
                  width: 150,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(999),
                    child: LinearProgressIndicator(
                      minHeight: 4,
                      backgroundColor: isDark
                          ? Colors.white.withValues(alpha: 0.08)
                          : NorinPalette.lightBorder,
                      color: NorinPalette.emeraldLight,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
