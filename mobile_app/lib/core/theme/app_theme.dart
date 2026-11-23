import 'package:flutter/material.dart';

class NorinPalette {
  // Primary Neon Violet / Magenta / Cyan Cosmic Palette
  static const emerald = Color(0xFFA855F7); // Primary electric violet
  static const emeraldDark = Color(0xFF7C3AED);
  static const emeraldLight = Color(0xFFC084FC); // Glowing lavender
  static const magenta = Color(0xFFE879F9);
  static const indigo = Color(0xFFD946EF); // Neon magenta accent
  static const sky = Color(0xFF38BDF8); // Neon cyan
  static const profit = Color(0xFF22C55E); // Neon mint green
  static const amber = Color(0xFFF59E0B);
  static const danger = Color(0xFFF43F5E);

  // Light Mode Surfaces (clean lavender-alabaster fallback)
  static const lightBg = Color(0xFFF4F3FA);
  static const lightCard = Color(0xFFFFFFFF);
  static const lightBorder = Color(0xFFE4E0F0);
  static const lightMuted = Color(0xFF645E7B);

  // Cosmic Obsidian Dark Mode Surfaces (reference theme)
  static const darkBg = Color(0xFF09080D);
  static const darkCard = Color(0xFF13121B);
  static const darkCardElevated = Color(0xFF1A1826);
  static const darkBorder = Color(0xFF272338);
  static const darkBorderGlow = Color(0xFF47376B);
  static const darkMuted = Color(0xFF8C87A6);

  static const neonPurpleGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFFE9D5FF), Color(0xFFC084FC), Color(0xFF9333EA)],
  );

  static const neonCyanGradient = LinearGradient(
    begin: Alignment.centerLeft,
    end: Alignment.centerRight,
    colors: [Color(0xFF93C5FD), Color(0xFF38BDF8), Color(0xFF6366F1)],
  );

  static const neonMagentaGradient = LinearGradient(
    begin: Alignment.centerLeft,
    end: Alignment.centerRight,
    colors: [Color(0xFFF0ABFC), Color(0xFFC084FC), Color(0xFF9333EA)],
  );

  static const heroGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF23183D), Color(0xFF161324), Color(0xFF121119)],
  );

  static const adminGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [Color(0xFF3A1A6E), Color(0xFF20153B), Color(0xFF121119)],
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
        primary: NorinPalette.emeraldDark,
        secondary: NorinPalette.sky,
        surface: NorinPalette.lightCard,
        error: NorinPalette.danger,
      ),
      scaffoldBackgroundColor: NorinPalette.lightBg,
    );
    return base.copyWith(
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        foregroundColor: Color(0xFF13111C),
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        color: NorinPalette.lightCard,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: NorinPalette.lightBorder, width: 1),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFFF9F8FE),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: NorinPalette.lightBorder),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: NorinPalette.lightBorder),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: NorinPalette.emeraldDark, width: 1.6),
        ),
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
        seedColor: NorinPalette.emerald,
        brightness: Brightness.dark,
        primary: NorinPalette.emeraldLight,
        onPrimary: const Color(0xFF130826),
        secondary: NorinPalette.sky,
        surface: NorinPalette.darkCard,
        onSurface: const Color(0xFFF5F3FF),
        onSurfaceVariant: NorinPalette.darkMuted,
        error: NorinPalette.danger,
      ),
      scaffoldBackgroundColor: NorinPalette.darkBg,
    );
    return base.copyWith(
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        foregroundColor: Color(0xFFF8F7FF),
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: const Color(0xFF151320),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(22),
          side: const BorderSide(color: NorinPalette.darkBorderGlow, width: 1),
        ),
      ),
      bottomSheetTheme: const BottomSheetThemeData(
        backgroundColor: Color(0xFF13121C),
        modalBackgroundColor: Color(0xFF13121C),
        surfaceTintColor: Colors.transparent,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(26)),
        ),
      ),
      cardTheme: CardThemeData(
        color: NorinPalette.darkCard,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: NorinPalette.darkBorder, width: 1),
        ),
      ),
      chipTheme: base.chipTheme.copyWith(
        backgroundColor: NorinPalette.darkCardElevated,
        selectedColor: NorinPalette.emerald.withValues(alpha: 0.24),
        side: const BorderSide(color: NorinPalette.darkBorder),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFF151320),
        hintStyle: const TextStyle(color: NorinPalette.darkMuted),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: NorinPalette.darkBorder),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: NorinPalette.darkBorder),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: NorinPalette.emeraldLight, width: 1.6),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: NorinPalette.emerald,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: const Color(0xFFEDE9FE),
          side: const BorderSide(color: NorinPalette.darkBorderGlow),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        ),
      ),
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: NorinPalette.emerald,
        foregroundColor: Colors.white,
        elevation: 6,
      ),
      dividerTheme: const DividerThemeData(
        color: NorinPalette.darkBorder,
        thickness: 1,
        space: 1,
      ),
    );
  }
}
