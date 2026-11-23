import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_client.dart';
import '../theme/app_theme.dart';

const tNumStyle = TextStyle(fontFeatures: [FontFeature.tabularFigures()]);

void showSnack(BuildContext context, String msg, {bool error = false}) {
  if (error) {
    HapticFeedback.mediumImpact();
  } else {
    HapticFeedback.lightImpact();
  }
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        content: Row(
          children: [
            TweenAnimationBuilder<double>(
              tween: Tween(begin: 0.4, end: 1.0),
              duration: const Duration(milliseconds: 280),
              curve: Curves.elasticOut,
              builder: (_, v, child) => Transform.scale(scale: v, child: child),
              child: Icon(
                error ? Icons.error_outline_rounded : Icons.check_circle_rounded,
                color: Colors.white,
                size: 19,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                msg,
                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
              ),
            ),
          ],
        ),
        behavior: SnackBarBehavior.floating,
        backgroundColor: error ? NorinPalette.danger : NorinPalette.emeraldDark,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    );
}

class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title, this.trailing});

  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(
            title,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
          ),
        ),
        ?trailing,
      ],
    );
  }
}

class AsyncErrorCard extends StatelessWidget {
  const AsyncErrorCard({super.key, required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.cloud_off_rounded, size: 42, color: NorinPalette.danger),
                const SizedBox(height: 12),
                Text(
                  ApiClient.extractError(error),
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 14),
                FilledButton.icon(
                  onPressed: onRetry,
                  icon: const Icon(Icons.refresh_rounded),
                  label: const Text("Qayta urinish"),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class StatusBadge extends StatelessWidget {
  const StatusBadge({super.key, required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.3)),
      ),
      child: Text(
        label,
        style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class SpinningRefreshButton extends StatefulWidget {
  const SpinningRefreshButton({
    super.key,
    required this.onRefresh,
    this.tooltip = 'Yangilash',
    this.glassCircle = false,
  });

  final FutureOr<void> Function() onRefresh;
  final String tooltip;
  final bool glassCircle;

  @override
  State<SpinningRefreshButton> createState() => _SpinningRefreshButtonState();
}

class _SpinningRefreshButtonState extends State<SpinningRefreshButton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  bool _spinning = false;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 650),
    );
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  Future<void> _handleTap() async {
    if (_spinning) return;
    setState(() => _spinning = true);
    _ctrl.repeat();
    try {
      await Future.wait([
        Future<void>.sync(widget.onRefresh),
        Future<void>.delayed(const Duration(milliseconds: 650)),
      ]);
    } catch (_) {
      // Errors are surfaced by provider error cards; stop spinner cleanly.
    } finally {
      if (mounted) {
        final remainingMs = math.max(120, ((1.0 - _ctrl.value) * 450).round());
        await _ctrl.animateTo(
          1.0,
          duration: Duration(milliseconds: remainingMs),
          curve: Curves.easeOut,
        );
        if (mounted) {
          _ctrl.value = 0;
          setState(() => _spinning = false);
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final rotatedIcon = RotationTransition(
      turns: _ctrl,
      child: Icon(Icons.refresh_rounded, size: widget.glassCircle ? 19 : 22),
    );

    if (widget.glassCircle) {
      final isDark = Theme.of(context).brightness == Brightness.dark;
      return Tooltip(
        message: widget.tooltip,
        child: InkWell(
          onTap: _spinning ? null : _handleTap,
          borderRadius: BorderRadius.circular(999),
          child: Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: isDark ? NorinPalette.darkCardElevated : NorinPalette.lightCard,
              border: Border.all(
                color: isDark ? NorinPalette.darkBorder : NorinPalette.lightBorder,
              ),
            ),
            child: rotatedIcon,
          ),
        ),
      );
    }

    return IconButton(
      tooltip: widget.tooltip,
      icon: rotatedIcon,
      onPressed: _spinning ? null : _handleTap,
    );
  }
}

/// Dynamic bottom padding for tab screens that sit behind the floating dock,
/// adapting to 3-button nav bars (~48dp), gesture pills (~20dp), or 0dp devices.
double dockBottomClearance(BuildContext context) {
  final inset = MediaQuery.viewPaddingOf(context).bottom;
  return 108 + inset;
}

/// Dynamic bottom padding for standalone screens & modal bottom sheets.
double screenBottomClearance(BuildContext context, {double extra = 24}) {
  return extra + MediaQuery.viewPaddingOf(context).bottom;
}

class PressableScale extends StatefulWidget {
  const PressableScale({
    super.key,
    required this.child,
    this.scaleFactor = 0.95,
    this.enabled = true,
    this.haptic = true,
    this.onTap,
  });

  final Widget child;
  final double scaleFactor;
  final bool enabled;
  final bool haptic;
  final VoidCallback? onTap;

  @override
  State<PressableScale> createState() => _PressableScaleState();
}

class _PressableScaleState extends State<PressableScale> {
  bool _pressed = false;

  void _setPressed(bool value) {
    if (_pressed != value && mounted) {
      setState(() => _pressed = value);
    }
  }

  @override
  Widget build(BuildContext context) {
    final content = Listener(
      behavior: HitTestBehavior.translucent,
      onPointerDown: widget.enabled
          ? (_) {
              if (widget.haptic) HapticFeedback.lightImpact();
              _setPressed(true);
            }
          : null,
      onPointerUp: (_) => _setPressed(false),
      onPointerCancel: (_) => _setPressed(false),
      child: AnimatedScale(
        scale: (widget.enabled && _pressed) ? widget.scaleFactor : 1.0,
        duration: const Duration(milliseconds: 110),
        curve: Curves.easeOutCubic,
        child: widget.child,
      ),
    );
    if (widget.onTap != null && widget.enabled) {
      return GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: widget.onTap,
        child: content,
      );
    }
    return content;
  }
}

class AnimatedCountText extends StatefulWidget {
  const AnimatedCountText({
    super.key,
    required this.value,
    required this.formatter,
    this.style,
    this.duration = const Duration(milliseconds: 680),
    this.maxLines = 1,
  });

  final double value;
  final String Function(double) formatter;
  final TextStyle? style;
  final Duration duration;
  final int maxLines;

  @override
  State<AnimatedCountText> createState() => _AnimatedCountTextState();
}

class _AnimatedCountTextState extends State<AnimatedCountText> {
  double _begin = 0;

  @override
  void didUpdateWidget(covariant AnimatedCountText oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.value != widget.value) {
      _begin = oldWidget.value;
    }
  }

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween<double>(begin: _begin, end: widget.value),
      duration: widget.duration,
      curve: Curves.easeOutCubic,
      builder: (_, v, _) => Text(
        widget.formatter(v),
        maxLines: widget.maxLines,
        overflow: TextOverflow.ellipsis,
        style: widget.style,
      ),
    );
  }
}

class CosmicShimmerBox extends StatefulWidget {
  const CosmicShimmerBox({
    super.key,
    this.width = double.infinity,
    required this.height,
    this.borderRadius = 18,
  });

  final double width;
  final double height;
  final double borderRadius;

  @override
  State<CosmicShimmerBox> createState() => _CosmicShimmerBoxState();
}

class _CosmicShimmerBoxState extends State<CosmicShimmerBox>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final low = isDark ? const Color(0xFF1D1930) : const Color(0xFFE8E3F8);
    final high = isDark ? const Color(0xFF2A2442) : const Color(0xFFF4F1FC);
    return AnimatedBuilder(
      animation: _ctrl,
      builder: (_, _) => Container(
        width: widget.width,
        height: widget.height,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(widget.borderRadius),
          color: Color.lerp(low, high, Curves.easeInOut.transform(_ctrl.value)),
        ),
      ),
    );
  }
}
