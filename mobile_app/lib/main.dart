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

    Widget home;
    if (auth.stage == AuthStage.loading) {
      home = const _SplashView();
    } else if (auth.stage == AuthStage.unauthenticated) {
      home = const LoginScreen();
    } else if (bioLock.locked) {
      home = const BiometricLockScreen();
    } else {
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
      home: home,
    );
  }
}

class _SplashView extends StatelessWidget {
  const _SplashView();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: CosmicBackground(
        showBottomHorizonGlow: true,
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const GlowingSquircleEmblem(size: 98),
              const SizedBox(height: 12),
              const Text(
                "Sotuv AI",
                style: TextStyle(fontSize: 23, fontWeight: FontWeight.w900, letterSpacing: -0.3),
              ),
              const SizedBox(height: 4),
              Text(
                "Savdo, qarz va kassa daftari",
                style: TextStyle(
                  fontSize: 12.5,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: 26,
                height: 26,
                child: CircularProgressIndicator(
                  strokeWidth: 2.6,
                  color: NorinPalette.emeraldLight,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
