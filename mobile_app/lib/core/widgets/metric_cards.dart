import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../theme/app_theme.dart';
import 'norin_widgets.dart';

double asDouble(dynamic v, [double fallback = 0]) {
  if (v is num) return v.toDouble();
  if (v is String) return double.tryParse(v) ?? fallback;
  return fallback;
}

int asInt(dynamic v, [int fallback = 0]) {
  if (v is int) return v;
  if (v is num) return v.toInt();
  if (v is String) return int.tryParse(v) ?? fallback;
  return fallback;
}

String asStr(dynamic v, [String fallback = '']) {
  if (v == null) return fallback;
  return v.toString();
}

Map<String, dynamic> asMap(dynamic v) {
  if (v is Map<String, dynamic>) return v;
  if (v is Map) return Map<String, dynamic>.from(v);
  return <String, dynamic>{};
}

List<Map<String, dynamic>> asMapList(dynamic v) {
  if (v is List) {
    return v.map((e) => asMap(e)).toList();
  }
  return <Map<String, dynamic>>[];
}

class CosmicBackground extends StatelessWidget {
  const CosmicBackground({
    super.key,
    required this.child,
    this.showBottomHorizonGlow = false,
  });

  final Widget child;
  final bool showBottomHorizonGlow;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    if (!isDark) {
      return Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topRight,
            end: Alignment.bottomLeft,
            colors: [Color(0xFFECE7FE), Color(0xFFF5F4FB), Color(0xFFF8FAFC)],
          ),
        ),
        child: child,
      );
    }

    return Container(
      color: NorinPalette.darkBg,
      child: Stack(
        fit: StackFit.expand,
        children: [
          Positioned(
            top: -120,
            right: -80,
            child: IgnorePointer(
              child: Container(
                width: 340,
                height: 340,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: [
                      NorinPalette.emerald.withValues(alpha: 0.24),
                      NorinPalette.indigo.withValues(alpha: 0.08),
                      Colors.transparent,
                    ],
                  ),
                ),
              ),
            ),
          ),
          Positioned(
            top: 90,
            left: -130,
            child: IgnorePointer(
              child: Container(
                width: 280,
                height: 280,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: [
                      NorinPalette.sky.withValues(alpha: 0.10),
                      Colors.transparent,
                    ],
                  ),
                ),
              ),
            ),
          ),
          if (showBottomHorizonGlow)
            Positioned(
              left: -40,
              right: -40,
              bottom: -140,
              child: IgnorePointer(
                child: Container(
                  height: 210,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(999),
                    gradient: RadialGradient(
                      center: Alignment.topCenter,
                      radius: 0.9,
                      colors: [
                        NorinPalette.indigo.withValues(alpha: 0.42),
                        NorinPalette.emeraldDark.withValues(alpha: 0.16),
                        Colors.transparent,
                      ],
                    ),
                  ),
                ),
              ),
            ),
          child,
        ],
      ),
    );
  }
}

class SpotlightHeroCard extends StatelessWidget {
  const SpotlightHeroCard({
    super.key,
    required this.child,
    this.glowColor = NorinPalette.emeraldLight,
    this.accentColor = NorinPalette.indigo,
    this.padding = const EdgeInsets.all(20),
    this.borderRadius = 22,
  });

  final Widget child;
  final Color glowColor;
  final Color accentColor;
  final EdgeInsetsGeometry padding;
  final double borderRadius;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    if (!isDark) {
      return Container(
        padding: padding,
        decoration: BoxDecoration(
          gradient: NorinPalette.heroGradient,
          borderRadius: BorderRadius.circular(borderRadius),
          boxShadow: [
            BoxShadow(
              color: NorinPalette.emeraldDark.withValues(alpha: 0.28),
              blurRadius: 20,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: DefaultTextStyle.merge(
          style: const TextStyle(color: Colors.white),
          child: child,
        ),
      );
    }

    return ClipRRect(
      borderRadius: BorderRadius.circular(borderRadius),
      child: Container(
        decoration: BoxDecoration(
          color: const Color(0xFF14121E),
          borderRadius: BorderRadius.circular(borderRadius),
          border: Border.all(color: glowColor.withValues(alpha: 0.34), width: 1),
          boxShadow: [
            BoxShadow(
              color: glowColor.withValues(alpha: 0.16),
              blurRadius: 24,
              offset: const Offset(0, 8),
            ),
          ],
        ),
        child: Stack(
          children: [
            Positioned.fill(
              child: IgnorePointer(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: RadialGradient(
                      center: const Alignment(0, -1.15),
                      radius: 1.25,
                      colors: [
                        glowColor.withValues(alpha: 0.28),
                        accentColor.withValues(alpha: 0.10),
                        Colors.transparent,
                      ],
                    ),
                  ),
                ),
              ),
            ),
            Positioned(
              top: 0,
              left: 34,
              right: 34,
              child: Container(
                height: 2.5,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(999),
                  gradient: LinearGradient(
                    colors: [
                      Colors.transparent,
                      glowColor,
                      accentColor,
                      Colors.transparent,
                    ],
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: glowColor.withValues(alpha: 0.8),
                      blurRadius: 12,
                    ),
                  ],
                ),
              ),
            ),
            Padding(padding: padding, child: child),
          ],
        ),
      ),
    );
  }
}

class GlowingSquircleEmblem extends StatelessWidget {
  const GlowingSquircleEmblem({super.key, this.size = 112});
  final double size;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size * 1.9,
      height: size * 1.65,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Container(
            width: size * 1.75,
            height: size * 1.55,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: RadialGradient(
                colors: [
                  NorinPalette.indigo.withValues(alpha: 0.48),
                  NorinPalette.emerald.withValues(alpha: 0.22),
                  Colors.transparent,
                ],
              ),
            ),
          ),
          // Vertical subtle cosmic light beam
          Container(
            width: 3,
            height: size * 1.55,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [
                  Colors.transparent,
                  NorinPalette.magenta.withValues(alpha: 0.65),
                  Colors.transparent,
                ],
              ),
            ),
          ),
          // Orbital hairline ring
          Transform.rotate(
            angle: -0.25,
            child: Container(
              width: size * 1.38,
              height: size * 0.72,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(999),
                border: Border.all(
                  color: Colors.white.withValues(alpha: 0.16),
                  width: 1,
                ),
              ),
            ),
          ),
          // Tilted 3D glass squircle
          Transform.rotate(
            angle: -0.16,
            child: Container(
              width: size,
              height: size,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(size * 0.28),
                gradient: const LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [
                    Color(0xFF4C1D95),
                    Color(0xFF211138),
                    Color(0xFF100C1C),
                  ],
                ),
                border: Border.all(
                  color: NorinPalette.magenta.withValues(alpha: 0.75),
                  width: 2.0,
                ),
                boxShadow: [
                  BoxShadow(
                    color: NorinPalette.indigo.withValues(alpha: 0.55),
                    blurRadius: 28,
                    spreadRadius: 1,
                  ),
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.65),
                    blurRadius: 16,
                    offset: const Offset(0, 10),
                  ),
                ],
              ),
              child: Container(
                margin: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(size * 0.22),
                  gradient: const LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [Color(0xFF1A1230), Color(0xFF0A0812)],
                  ),
                  border: Border.all(
                    color: Colors.white.withValues(alpha: 0.15),
                    width: 1,
                  ),
                ),
                child: CustomPaint(
                  painter: _SotuvAiEmblemPainter(),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _SotuvAiEmblemPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;

    // 3 ascending sales bars along bottom-left
    final barColors = [
      NorinPalette.indigo.withValues(alpha: 0.78),
      NorinPalette.magenta.withValues(alpha: 0.88),
      const Color(0xFFF5D0FE),
    ];
    final barHeights = [0.14, 0.22, 0.31];
    final barW = w * 0.11;
    final baseY = h * 0.80;
    for (int i = 0; i < 3; i++) {
      final bx = w * (0.20 + i * 0.145);
      final bh = h * barHeights[i];
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(bx, baseY - bh, barW, bh),
          Radius.circular(w * 0.03),
        ),
        Paint()..color = barColors[i],
      );
    }

    // Dynamic upward sales growth trend arrow
    final trendPath = Path()
      ..moveTo(w * 0.21, h * 0.52)
      ..lineTo(w * 0.40, h * 0.36)
      ..lineTo(w * 0.53, h * 0.44)
      ..lineTo(w * 0.79, h * 0.20);

    final glowPaint = Paint()
      ..style = PaintingStyle.stroke
      ..color = NorinPalette.magenta.withValues(alpha: 0.55)
      ..strokeWidth = w * 0.12
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 5);
    canvas.drawPath(trendPath, glowPaint);

    final linePaint = Paint()
      ..style = PaintingStyle.stroke
      ..shader = const LinearGradient(
        begin: Alignment.bottomLeft,
        end: Alignment.topRight,
        colors: [Color(0xFFF5D0FE), Color(0xFFFFFFFF)],
      ).createShader(Rect.fromLTWH(0, 0, w, h))
      ..strokeWidth = w * 0.075
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    canvas.drawPath(trendPath, linePaint);

    final headPath = Path()
      ..moveTo(w * 0.62, h * 0.20)
      ..lineTo(w * 0.79, h * 0.20)
      ..lineTo(w * 0.79, h * 0.37);
    canvas.drawPath(headPath, glowPaint);
    canvas.drawPath(headPath, linePaint);

    // 4-point AI sparkle star (top-left)
    final sx = w * 0.23;
    final sy = h * 0.26;
    final sr = w * 0.095;
    final si = sr * 0.28;
    final star = Path()
      ..moveTo(sx, sy - sr)
      ..lineTo(sx + si, sy - si)
      ..lineTo(sx + sr, sy)
      ..lineTo(sx + si, sy + si)
      ..lineTo(sx, sy + sr)
      ..lineTo(sx - si, sy + si)
      ..lineTo(sx - sr, sy)
      ..lineTo(sx - si, sy - si)
      ..close();
    canvas.drawPath(star, Paint()..color = const Color(0xFFF5D0FE));

    // Glowing coin/target accent at bottom-right
    final dotCenter = Offset(w * 0.73, h * 0.71);
    canvas.drawCircle(
      dotCenter,
      w * 0.095,
      Paint()..color = NorinPalette.magenta.withValues(alpha: 0.40),
    );
    canvas.drawCircle(
      dotCenter,
      w * 0.055,
      Paint()..color = const Color(0xFFFFFFFF),
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class NeonPillButton extends StatelessWidget {
  const NeonPillButton({
    super.key,
    required this.onPressed,
    required this.label,
    this.icon,
    this.busy = false,
  });

  final VoidCallback? onPressed;
  final String label;
  final IconData? icon;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final enabled = onPressed != null && !busy;
    return Opacity(
      opacity: enabled ? 1.0 : 0.65,
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(999),
          gradient: NorinPalette.neonPurpleGradient,
          boxShadow: [
            BoxShadow(
              color: NorinPalette.emerald.withValues(alpha: 0.55),
              blurRadius: 20,
              offset: const Offset(0, 6),
            ),
          ],
        ),
        child: Material(
          color: Colors.transparent,
          child: InkWell(
            onTap: enabled ? onPressed : null,
            borderRadius: BorderRadius.circular(999),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 15),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (busy)
                    const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2.2,
                        color: Colors.white,
                      ),
                    )
                  else if (icon != null)
                    Icon(icon, size: 19, color: const Color(0xFF1A0B2E)),
                  if (busy || icon != null) const SizedBox(width: 8),
                  Flexible(
                    child: FittedBox(
                      fit: BoxFit.scaleDown,
                      child: Text(
                        label,
                        maxLines: 1,
                        style: const TextStyle(
                          color: Color(0xFF1A0B2E),
                          fontSize: 15.5,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 0.1,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class KpiCardTile extends StatelessWidget {
  const KpiCardTile({
    super.key,
    required this.title,
    required this.value,
    required this.icon,
    required this.color,
    this.subtitle,
    this.onTap,
    this.highlight = false,
  });

  final String title;
  final String value;
  final String? subtitle;
  final IconData icon;
  final Color color;
  final VoidCallback? onTap;
  final bool highlight;

  @override
  Widget build(BuildContext context) {
    final tt = Theme.of(context).textTheme;
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final useSpotlight = highlight || color == NorinPalette.emerald;

    return ClipRRect(
      borderRadius: BorderRadius.circular(20),
      child: Material(
        color: isDark
            ? (useSpotlight ? const Color(0xFF171324) : NorinPalette.darkCard)
            : NorinPalette.lightCard,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(
            color: useSpotlight
                ? color.withValues(alpha: isDark ? 0.5 : 0.35)
                : (isDark ? NorinPalette.darkBorder : NorinPalette.lightBorder),
            width: 1,
          ),
        ),
        child: InkWell(
          onTap: onTap,
          child: Stack(
            children: [
              if (useSpotlight && isDark)
                Positioned.fill(
                  child: IgnorePointer(
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: RadialGradient(
                          center: const Alignment(0, -1.1),
                          radius: 1.2,
                          colors: [
                            color.withValues(alpha: 0.25),
                            Colors.transparent,
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              if (useSpotlight)
                Positioned(
                  top: 0,
                  left: 24,
                  right: 24,
                  child: Container(
                    height: 2.2,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(999),
                      gradient: LinearGradient(
                        colors: [Colors.transparent, color, Colors.transparent],
                      ),
                    ),
                  ),
                ),
              Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        Container(
                          width: 8,
                          height: 8,
                          decoration: BoxDecoration(
                            color: color,
                            shape: BoxShape.circle,
                            boxShadow: [
                              BoxShadow(color: color.withValues(alpha: 0.7), blurRadius: 6),
                            ],
                          ),
                        ),
                        const SizedBox(width: 7),
                        Expanded(
                          child: Text(
                            title.toUpperCase(),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: tt.labelSmall?.copyWith(
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                              fontWeight: FontWeight.w700,
                              letterSpacing: 0.4,
                              fontSize: 10.5,
                            ),
                          ),
                        ),
                        Icon(icon, size: 16, color: color.withValues(alpha: 0.85)),
                      ],
                    ),
                    const SizedBox(height: 8),
                    FittedBox(
                      fit: BoxFit.scaleDown,
                      alignment: Alignment.centerLeft,
                      child: Text(
                        value,
                        style: tt.titleLarge?.merge(tNumStyle).copyWith(
                              fontWeight: FontWeight.w800,
                              letterSpacing: -0.3,
                            ),
                      ),
                    ),
                    if (subtitle != null && subtitle!.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        subtitle!,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: tt.labelSmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class EmptyStateCard extends StatelessWidget {
  const EmptyStateCard({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
    this.action,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: cs.primary.withValues(alpha: 0.14),
                shape: BoxShape.circle,
              ),
              child: Icon(icon, size: 32, color: cs.primary),
            ),
            const SizedBox(height: 12),
            Text(
              title,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
            ),
            if (subtitle != null) ...[
              const SizedBox(height: 6),
              Text(
                subtitle!,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: cs.onSurfaceVariant,
                    ),
              ),
            ],
            if (action != null) ...[
              const SizedBox(height: 14),
              action!,
            ],
          ],
        ),
      ),
    );
  }
}

Future<void> runExcelAction(
  BuildContext context,
  ApiClient api, {
  required String path,
  required String filename,
  Map<String, dynamic>? query,
  required bool share,
}) async {
  showSnack(context, "Excel tayyorlanmoqda...");
  try {
    await api.openOrShareExcel(path, filename, query: query, share: share);
  } catch (e) {
    if (context.mounted) {
      showSnack(context, ApiClient.extractError(e), error: true);
    }
  }
}

Future<void> showExcelActionPicker(
  BuildContext context,
  ApiClient api, {
  required String title,
  required String path,
  required String filename,
  Map<String, dynamic>? query,
}) async {
  await showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(ctx).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(filename, style: Theme.of(ctx).textTheme.bodySmall),
            const SizedBox(height: 16),
            ListTile(
              leading: CircleAvatar(
                backgroundColor: NorinPalette.emerald.withValues(alpha: 0.16),
                child: const Icon(Icons.open_in_new_rounded, color: NorinPalette.emeraldLight),
              ),
              title: const Text("Telefonda ochish"),
              subtitle: const Text("Excel dasturida ko'rish"),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
              onTap: () {
                Navigator.pop(ctx);
                runExcelAction(context, api, path: path, filename: filename, query: query, share: false);
              },
            ),
            const SizedBox(height: 8),
            ListTile(
              leading: CircleAvatar(
                backgroundColor: NorinPalette.sky.withValues(alpha: 0.16),
                child: const Icon(Icons.share_rounded, color: NorinPalette.sky),
              ),
              title: const Text("Ulashish (Telegram / WhatsApp)"),
              subtitle: const Text("Faylni yuborish yoki saqlash"),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
              onTap: () {
                Navigator.pop(ctx);
                runExcelAction(context, api, path: path, filename: filename, query: query, share: true);
              },
            ),
          ],
        ),
      ),
    ),
  );
}

Future<bool> showConfirmDialog(
  BuildContext context, {
  required String title,
  required String message,
  String confirmLabel = "Tasdiqlash",
  bool destructive = false,
}) async {
  final res = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx, false),
          child: const Text("Bekor qilish"),
        ),
        FilledButton(
          style: destructive
              ? FilledButton.styleFrom(backgroundColor: NorinPalette.danger)
              : null,
          onPressed: () => Navigator.pop(ctx, true),
          child: Text(confirmLabel),
        ),
      ],
    ),
  );
  return res == true;
}
