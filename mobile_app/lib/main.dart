import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/state/providers.dart';
import 'core/theme/app_theme.dart';
import 'core/widgets/metric_cards.dart';
import 'features/auth/login_screen.dart';
import 'features/shell/main_shell.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const ProviderScope(child: NorinAiApp()));
}

class NorinAiApp extends ConsumerStatefulWidget {
  const NorinAiApp({super.key});

  @override
  ConsumerState<NorinAiApp> createState() => _NorinAiAppState();
}

class _NorinAiAppState extends ConsumerState<NorinAiApp> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(authProvider.notifier).bootstrap());
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final themeMode = ref.watch(themeModeProvider);

    return MaterialApp(
      title: 'Norin AI Hisobot',
      debugShowCheckedModeBanner: false,
      themeMode: themeMode,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      home: switch (auth.stage) {
        AuthStage.loading => const _SplashView(),
        AuthStage.unauthenticated => const LoginScreen(),
        AuthStage.authenticated => const MainShell(),
      },
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
                "Norin AI Hisobot",
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, letterSpacing: -0.3),
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
