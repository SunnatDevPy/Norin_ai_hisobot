import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/state/providers.dart';
import 'core/theme/app_theme.dart';
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
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                gradient: NorinPalette.heroGradient,
                borderRadius: BorderRadius.circular(24),
              ),
              child: const Icon(Icons.analytics_rounded, size: 42, color: Colors.white),
            ),
            const SizedBox(height: 18),
            const Text(
              "Norin AI Hisobot",
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
            ),
            const SizedBox(height: 14),
            const SizedBox(
              width: 28,
              height: 28,
              child: CircularProgressIndicator(strokeWidth: 2.8),
            ),
          ],
        ),
      ),
    );
  }
}
