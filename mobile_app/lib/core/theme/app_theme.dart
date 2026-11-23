import 'package:flutter/material.dart';

class NorinPalette {
  static const emerald = Color(0xFF0D9488);
  static const emeraldDark = Color(0xFF0F766E);
  static const emeraldLight = Color(0xFF14B8A6);
  static const amber = Color(0xFFF59E0B);
  static const profit = Color(0xFF059669);
  static const danger = Color(0xFFDC2626);
  static const indigo = Color(0xFF4F46E5);
  static const sky = Color(0xFF0284C7);

  static const lightBg = Color(0xFFF3F6FA);
  static const lightCard = Color(0xFFFFFFFF);
  static const lightBorder = Color(0xFFE2E8F0);
  static const lightMuted = Color(0xFF64748B);

  static const darkBg = Color(0xFF0B1220);
  static const darkCard = Color(0xFF131D2E);
  static const darkBorder = Color(0xFF1E293B);
  static const darkMuted = Color(0xFF94A3B8);

  static const heroGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF0F766E), Color(0xFF0D9488), Color(0xFF047857)],
  );

  static const adminGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF312E81), Color(0xFF4F46E5), Color(0xFF0F766E)],
  );
}

class AppTheme {
  static ThemeData light() {
    final base = ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: ColorScheme.fromSeed(
        seedColor: NorinPalette.emerald,
        brightness: Brightness.light,
        primary: NorinPalette.emerald,
        secondary: NorinPalette.amber,
        surface: NorinPalette.lightCard,
        error: NorinPalette.danger,
      ),
      scaffoldBackgroundColor: NorinPalette.lightBg,
    );
    return base.copyWith(
      appBarTheme: const AppBarTheme(
        backgroundColor: NorinPalette.lightBg,
        foregroundColor: Color(0xFF0F172A),
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        color: NorinPalette.lightCard,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(18),
          side: const BorderSide(color: NorinPalette.lightBorder, width: 1),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFFF8FAFC),
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: NorinPalette.lightBorder),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: NorinPalette.lightBorder),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: NorinPalette.emerald, width: 1.6),
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: NorinPalette.lightCard,
        indicatorColor: NorinPalette.emerald.withValues(alpha: 0.14),
        elevation: 8,
        height: 68,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
      ),
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: NorinPalette.emerald,
        foregroundColor: Colors.white,
        elevation: 3,
      ),
      dividerTheme: const DividerThemeData(
        color: NorinPalette.lightBorder,
        thickness: 1,
        space: 1,
      ),
    );
  }

  static ThemeData dark() {
    final base = ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: ColorScheme.fromSeed(
        seedColor: NorinPalette.emeraldLight,
        brightness: Brightness.dark,
        primary: NorinPalette.emeraldLight,
        secondary: NorinPalette.amber,
        surface: NorinPalette.darkCard,
        error: const Color(0xFFF87171),
      ),
      scaffoldBackgroundColor: NorinPalette.darkBg,
    );
    return base.copyWith(
      appBarTheme: const AppBarTheme(
        backgroundColor: NorinPalette.darkBg,
        foregroundColor: Colors.white,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        color: NorinPalette.darkCard,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(18),
          side: const BorderSide(color: NorinPalette.darkBorder, width: 1),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFF0F172A),
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: NorinPalette.darkBorder),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: NorinPalette.darkBorder),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(14),
          borderSide: const BorderSide(color: NorinPalette.emeraldLight, width: 1.6),
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: NorinPalette.darkCard,
        indicatorColor: NorinPalette.emeraldLight.withValues(alpha: 0.2),
        elevation: 8,
        height: 68,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
      ),
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: NorinPalette.emeraldLight,
        foregroundColor: Color(0xFF06201D),
        elevation: 3,
      ),
      dividerTheme: const DividerThemeData(
        color: NorinPalette.darkBorder,
        thickness: 1,
        space: 1,
      ),
    );
  }
}
