import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:norin_ai_app/core/api/api_client.dart';
import 'package:norin_ai_app/core/theme/app_theme.dart';
import 'package:norin_ai_app/core/update/app_updater.dart';
import 'package:norin_ai_app/core/utils/formatters.dart';
import 'package:norin_ai_app/core/version.dart';
import 'package:norin_ai_app/core/widgets/norin_widgets.dart';
import 'package:norin_ai_app/features/auth/login_screen.dart';

void main() {
  test('Uzbek formatters produce expected strings', () {
    expect(formatUzs(1150000), "1 150 000 so'm");
    expect(formatUzs(5000, withCurrency: false), "5 000");
    expect(formatCompactUzs(2500000), "2.5 mln");
    expect(formatCompactUzs(450000), "450k");
    expect(formatKg(10.0), "10 kg");
    expect(formatKg(2.55, unit: 'dona'), "2.55 dona");
  });

  test('AppUpdateInfo compares build numbers cleanly', () {
    final newer = AppUpdateInfo.fromJson({
      'version': '9.9.9',
      'build': kAppBuildNumber + 1,
      'full': '9.9.9+${kAppBuildNumber + 1}',
      'built_at': '2026-11-23',
      'size_bytes': 50000000,
      'apk_available': true,
    });
    expect(newer.hasUpdate, isTrue);

    final same = AppUpdateInfo.fromJson({
      'version': kAppVersion,
      'build': kAppBuildNumber,
      'apk_available': true,
    });
    expect(same.hasUpdate, isFalse);

    final unavailable = AppUpdateInfo.fromJson({
      'version': '9.9.9',
      'build': kAppBuildNumber + 5,
      'apk_available': false,
    });
    expect(unavailable.hasUpdate, isFalse);
  });

  testWidgets('LoginScreen renders 1-tap Telegram, ID-less code, and hides private ID/Server URL', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AppTheme.dark(),
          home: const LoginScreen(),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('Sotuv AI'), findsOneWidget);
    expect(find.text('Kirish'), findsAtLeastNWidgets(1));
    expect(find.text('Telegram orqali kirish'), findsOneWidget);
    expect(find.text('6 xonali kod'), findsOneWidget);

    final advancedTile = find.text('ID orqali kirish');
    await tester.ensureVisible(advancedTile);
    await tester.tap(advancedTile);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));

    expect(find.text('Telegram ID'), findsOneWidget);
    expect(find.text('Kod olish'), findsOneWidget);
    expect(find.text('Server manzili'), findsNothing);
    expect(find.textContaining('5649321700'), findsNothing);
    expect(find.textContaining('okaposai'), findsNothing);
  });

  testWidgets('LoginScreen renders cleanly in Light mode as well', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AppTheme.light(),
          home: const LoginScreen(),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('Sotuv AI'), findsOneWidget);
    expect(find.text('Kirish'), findsAtLeastNWidgets(1));
    expect(find.text('Telegram orqali kirish'), findsOneWidget);
  });

  testWidgets('SpinningRefreshButton animates and invokes onRefresh callback', (tester) async {
    int calls = 0;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.dark(),
        home: Scaffold(
          appBar: AppBar(
            actions: [
              SpinningRefreshButton(
                glassCircle: true,
                onRefresh: () async {
                  calls++;
                  await Future<void>.delayed(const Duration(milliseconds: 50));
                },
              ),
            ],
          ),
        ),
      ),
    );

    await tester.tap(find.byIcon(Icons.refresh_rounded));
    await tester.pump();
    expect(calls, 1);

    // Advance past minimum 650ms spin + settle animation cleanly without pending timers.
    await tester.pump(const Duration(milliseconds: 700));
    await tester.pumpAndSettle();
  });

  testWidgets('Bottom clearances adapt to 3-button nav bar vs zero-inset screens', (tester) async {
    late double dockWithBar;
    late double screenWithBar;
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(viewPadding: EdgeInsets.only(bottom: 48)),
        child: Builder(
          builder: (ctx) {
            dockWithBar = dockBottomClearance(ctx);
            screenWithBar = screenBottomClearance(ctx);
            return const SizedBox.shrink();
          },
        ),
      ),
    );
    expect(dockWithBar, 156);
    expect(screenWithBar, 72);

    late double dockNoBar;
    late double screenNoBar;
    await tester.pumpWidget(
      MediaQuery(
        data: const MediaQueryData(viewPadding: EdgeInsets.zero),
        child: Builder(
          builder: (ctx) {
            dockNoBar = dockBottomClearance(ctx);
            screenNoBar = screenBottomClearance(ctx);
            return const SizedBox.shrink();
          },
        ),
      ),
    );
    expect(dockNoBar, 108);
    expect(screenNoBar, 24);
  });

  testWidgets('PressableScale animates on press/release and fires callback', (tester) async {
    bool tapped = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: PressableScale(
              scaleFactor: 0.90,
              onTap: () => tapped = true,
              child: const SizedBox(
                width: 120,
                height: 48,
                child: Center(child: Text('Bosish')),
              ),
            ),
          ),
        ),
      ),
    );

    final gesture = await tester.startGesture(tester.getCenter(find.text('Bosish')));
    await tester.pump(const Duration(milliseconds: 120));
    final animatedDown = tester.widget<AnimatedScale>(find.byType(AnimatedScale));
    expect(animatedDown.scale, 0.90);

    await gesture.up();
    await tester.pumpAndSettle();
    final animatedUp = tester.widget<AnimatedScale>(find.byType(AnimatedScale));
    expect(animatedUp.scale, 1.0);
    expect(tapped, isTrue);
  });

  testWidgets('Horizontal swipe updates PageView index cleanly', (tester) async {
    int page = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PageView(
            onPageChanged: (idx) => page = idx,
            children: const [
              Center(child: Text('Sahifa 0')),
              Center(child: Text('Sahifa 1')),
              Center(child: Text('Sahifa 2')),
            ],
          ),
        ),
      ),
    );

    expect(page, 0);
    await tester.fling(find.byType(PageView), const Offset(-300, 0), 1000);
    await tester.pumpAndSettle();
    expect(page, 1);

    await tester.fling(find.byType(PageView), const Offset(300, 0), 1000);
    await tester.pumpAndSettle();
    expect(page, 0);
  });

  test('ApiClient.isPublicAuthPath allows auto-refresh on /auth/me and /auth/devices', () {
    expect(ApiClient.isPublicAuthPath('/auth/me'), isFalse);
    expect(ApiClient.isPublicAuthPath('/auth/devices'), isFalse);
    expect(ApiClient.isPublicAuthPath('/auth/logout'), isFalse);
    expect(ApiClient.isPublicAuthPath('/dashboard/summary'), isFalse);
    expect(ApiClient.isPublicAuthPath('/auth/refresh'), isTrue);
    expect(ApiClient.isPublicAuthPath('/auth/telegram-poll'), isTrue);
    expect(ApiClient.isPublicAuthPath('/auth/telegram-ticket'), isTrue);
    expect(ApiClient.isPublicAuthPath('/auth/login-code?x=1'), isTrue);
  });
}
