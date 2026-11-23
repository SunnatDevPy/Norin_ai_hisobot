import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../theme/app_theme.dart';

const tNumStyle = TextStyle(fontFeatures: [FontFeature.tabularFigures()]);

void showSnack(BuildContext context, String msg, {bool error = false}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        content: Text(msg),
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
