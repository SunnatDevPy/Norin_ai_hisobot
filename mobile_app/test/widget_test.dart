import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:norin_ai_app/core/theme/app_theme.dart';
import 'package:norin_ai_app/core/update/app_updater.dart';
import 'package:norin_ai_app/core/utils/formatters.dart';
import 'package:norin_ai_app/core/version.dart';
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
    expect(find.text('Tizimga kirish'), findsOneWidget);
    expect(find.text('Telegram orqali 1-bosishda kirish'), findsOneWidget);
    expect(find.text('6 xonali /apk kod'), findsOneWidget);

    final advancedTile = find.text('Telegram ID orqali kod olish');
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
}
