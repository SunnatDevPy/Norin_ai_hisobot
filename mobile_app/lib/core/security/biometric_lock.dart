import 'dart:io';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../state/providers.dart';
import '../theme/app_theme.dart';
import '../widgets/metric_cards.dart';
import '../widgets/norin_widgets.dart';

const MethodChannel _nativeChannel = MethodChannel('uz.norinai.norin_ai_app/installer');

class NativeBridge {
  static Future<bool> openExternalUrl(String url) async {
    try {
      final res = await _nativeChannel.invokeMethod<bool>('openExternalUrl', {'url': url});
      return res == true;
    } catch (_) {
      return false;
    }
  }

  static Future<bool> canAuthenticateBiometric() async {
    if (!Platform.isAndroid) return false;
    try {
      final res = await _nativeChannel.invokeMethod<bool>('canAuthenticateBiometric');
      return res == true;
    } catch (_) {
      return false;
    }
  }

  static Future<bool> authenticateBiometric({
    String title = "Sotuv AI Himoyasi",
    String subtitle = "Kirish uchun barmoq izini bosing",
  }) async {
    if (!Platform.isAndroid) return false;
    try {
      final res = await _nativeChannel.invokeMethod<bool>('authenticateBiometric', {
        'title': title,
        'subtitle': subtitle,
        'cancel': "Bekor qilish",
      });
      return res == true;
    } catch (_) {
      return false;
    }
  }
}

class BiometricLockState {
  const BiometricLockState({
    this.initialized = false,
    this.biometricAvailable = false,
    this.enabled = false,
    this.pinCode,
    this.locked = false,
    this.setupCompleted = false,
  });

  final bool initialized;
  final bool biometricAvailable;
  final bool enabled;
  final String? pinCode;
  final bool locked;
  final bool setupCompleted;

  bool get hasPin => pinCode != null && pinCode!.length == 4;
  bool get hasAnyLock => enabled || hasPin;

  BiometricLockState copyWith({
    bool? initialized,
    bool? biometricAvailable,
    bool? enabled,
    String? pinCode,
    bool clearPin = false,
    bool? locked,
    bool? setupCompleted,
  }) {
    return BiometricLockState(
      initialized: initialized ?? this.initialized,
      biometricAvailable: biometricAvailable ?? this.biometricAvailable,
      enabled: enabled ?? this.enabled,
      pinCode: clearPin ? null : (pinCode ?? this.pinCode),
      locked: locked ?? this.locked,
      setupCompleted: setupCompleted ?? this.setupCompleted,
    );
  }
}

class BiometricLockNotifier extends StateNotifier<BiometricLockState> {
  BiometricLockNotifier() : super(const BiometricLockState());

  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );
  static const _kBioKey = 'norin_biometric_enabled';
  static const _kPinKey = 'norin_pin_code';
  static const _kSetupDoneKey = 'norin_lock_setup_done';

  DateTime? _pausedAt;

  Future<void> init() async {
    final available = await NativeBridge.canAuthenticateBiometric();
    final bioRaw = await _storage.read(key: _kBioKey);
    final pinRaw = await _storage.read(key: _kPinKey);
    final setupDoneRaw = await _storage.read(key: _kSetupDoneKey);
    final enabled = bioRaw == '1' && available;
    final hasPin = pinRaw != null && pinRaw.length == 4;
    final setupCompleted = enabled || hasPin || setupDoneRaw == '1';
    state = BiometricLockState(
      initialized: true,
      biometricAvailable: available,
      enabled: enabled,
      pinCode: hasPin ? pinRaw : null,
      locked: enabled || hasPin,
      setupCompleted: setupCompleted,
    );
  }

  Future<void> markSetupCompleted() async {
    await _storage.write(key: _kSetupDoneKey, value: '1');
    state = state.copyWith(setupCompleted: true);
  }

  void onAppPaused() {
    if (state.hasAnyLock && !state.locked) {
      _pausedAt = DateTime.now();
    }
  }

  void onAppResumed() {
    final p = _pausedAt;
    _pausedAt = null;
    if (p == null || !state.hasAnyLock) return;
    if (DateTime.now().difference(p).inSeconds >= 45) {
      state = state.copyWith(locked: true);
    }
  }

  Future<bool> unlockWithBiometric() async {
    final ok = await NativeBridge.authenticateBiometric(
      title: "Sotuv AI",
      subtitle: "Davom etish uchun barmoq izini bosing",
    );
    if (ok) {
      state = state.copyWith(locked: false);
    }
    return ok;
  }

  bool unlockWithPin(String pin) {
    if (state.pinCode != null && pin == state.pinCode) {
      state = state.copyWith(locked: false);
      return true;
    }
    return false;
  }

  Future<bool> setBiometricEnabled(bool value) async {
    if (value) {
      final avail = await NativeBridge.canAuthenticateBiometric();
      if (!avail) return false;
      final ok = await NativeBridge.authenticateBiometric(
        title: "Otpechatkani yoqish",
        subtitle: "Tasdiqlash uchun barmoq izini bosing",
      );
      if (!ok) return false;
      await _storage.write(key: _kBioKey, value: '1');
      await _storage.write(key: _kSetupDoneKey, value: '1');
      state = state.copyWith(
        biometricAvailable: true,
        enabled: true,
        locked: false,
        setupCompleted: true,
      );
      return true;
    }
    await _storage.write(key: _kBioKey, value: '0');
    state = state.copyWith(enabled: false, locked: false);
    return true;
  }

  Future<void> setPinCode(String? pin) async {
    await _storage.write(key: _kSetupDoneKey, value: '1');
    if (pin == null || pin.trim().isEmpty) {
      await _storage.delete(key: _kPinKey);
      state = state.copyWith(clearPin: true, locked: false, setupCompleted: true);
      return;
    }
    final clean = pin.trim();
    await _storage.write(key: _kPinKey, value: clean);
    state = state.copyWith(pinCode: clean, locked: false, setupCompleted: true);
  }

  void resetSessionLock() {
    state = state.copyWith(locked: false);
  }
}

final biometricLockProvider =
    StateNotifierProvider<BiometricLockNotifier, BiometricLockState>((ref) {
  return BiometricLockNotifier();
});

class BiometricLockScreen extends ConsumerStatefulWidget {
  const BiometricLockScreen({super.key});

  @override
  ConsumerState<BiometricLockScreen> createState() => _BiometricLockScreenState();
}

class _BiometricLockScreenState extends ConsumerState<BiometricLockScreen> {
  String _pin = '';
  bool _authenticating = false;
  int _shakeNonce = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _tryBiometric());
  }

  Future<void> _tryBiometric() async {
    final lock = ref.read(biometricLockProvider);
    if (!lock.enabled || _authenticating) return;
    setState(() => _authenticating = true);
    await ref.read(biometricLockProvider.notifier).unlockWithBiometric();
    if (mounted) setState(() => _authenticating = false);
  }

  void _onDigit(String d) {
    if (_pin.length >= 4) return;
    setState(() => _pin += d);
    if (_pin.length == 4) {
      final ok = ref.read(biometricLockProvider.notifier).unlockWithPin(_pin);
      if (!ok) {
        HapticFeedback.heavyImpact();
        showSnack(context, "PIN-kod noto'g'ri", error: true);
        setState(() {
          _pin = '';
          _shakeNonce++;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final lock = ref.watch(biometricLockProvider);

    return Scaffold(
      body: CosmicBackground(
        showBottomHorizonGlow: true,
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 18),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 380),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const GlowingSquircleEmblem(size: 82),
                    const SizedBox(height: 8),
                    const Text(
                      "Sotuv AI Himoyalangan",
                      style: TextStyle(fontSize: 21, fontWeight: FontWeight.w900),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      lock.hasPin
                          ? "Barmoq izi yoki 4 xonali PIN-kod bilan oching"
                          : "Kirish uchun barmoq izini tasdiqlang",
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 13,
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 22),
                    if (lock.hasPin) ...[
                      Builder(
                        builder: (context) {
                          final isDark = Theme.of(context).brightness == Brightness.dark;
                          return TweenAnimationBuilder<double>(
                            key: ValueKey('pin_shake_$_shakeNonce'),
                            tween: Tween(begin: 0, end: _shakeNonce == 0 ? 0 : 1),
                            duration: const Duration(milliseconds: 360),
                            builder: (context, v, child) => Transform.translate(
                              offset: Offset(math.sin(v * math.pi * 4) * (1 - v) * 12, 0),
                              child: child,
                            ),
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: List.generate(4, (i) {
                                final filled = i < _pin.length;
                                return AnimatedScale(
                                  scale: filled ? 1.15 : 1.0,
                                  duration: const Duration(milliseconds: 140),
                                  curve: Curves.easeOutBack,
                                  child: AnimatedContainer(
                                    duration: const Duration(milliseconds: 150),
                                    width: 16,
                                    height: 16,
                                    margin: const EdgeInsets.symmetric(horizontal: 10),
                                    decoration: BoxDecoration(
                                      shape: BoxShape.circle,
                                      color: filled
                                          ? (isDark
                                              ? NorinPalette.emeraldLight
                                              : NorinPalette.emeraldDark)
                                          : Colors.transparent,
                                      border: Border.all(
                                        color: filled
                                            ? NorinPalette.magenta
                                            : (isDark
                                                ? NorinPalette.darkBorderGlow
                                                : NorinPalette.emeraldDark.withValues(alpha: 0.45)),
                                        width: 1.8,
                                      ),
                                      boxShadow: filled
                                          ? [
                                              BoxShadow(
                                                color: NorinPalette.emerald.withValues(alpha: 0.6),
                                                blurRadius: 10,
                                              ),
                                            ]
                                          : null,
                                    ),
                                  ),
                                );
                              }),
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 22),
                      _PinPad(
                        onDigit: _onDigit,
                        onBackspace: () {
                          if (_pin.isNotEmpty) {
                            setState(() => _pin = _pin.substring(0, _pin.length - 1));
                          }
                        },
                        onBiometric: lock.enabled ? _tryBiometric : null,
                      ),
                    ] else ...[
                      const SizedBox(height: 12),
                      NeonPillButton(
                        onPressed: _authenticating ? null : _tryBiometric,
                        busy: _authenticating,
                        icon: Icons.fingerprint_rounded,
                        label: "Otpechatka bilan ochish",
                      ),
                    ],
                    const SizedBox(height: 18),
                    TextButton(
                      onPressed: () async {
                        ref.read(biometricLockProvider.notifier).resetSessionLock();
                        await ref.read(authProvider.notifier).logout();
                      },
                      child: const Text(
                        "Boshqa hisobdan kirish (Chiqish)",
                        style: TextStyle(fontSize: 12.5),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _PinPad extends StatelessWidget {
  const _PinPad({
    required this.onDigit,
    required this.onBackspace,
    this.onBiometric,
  });

  final ValueChanged<String> onDigit;
  final VoidCallback onBackspace;
  final VoidCallback? onBiometric;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    Widget keyBtn(String label, {VoidCallback? onTap, Widget? child}) {
      return Padding(
        padding: const EdgeInsets.all(6),
        child: PressableScale(
          scaleFactor: 0.90,
          child: Material(
            color: isDark ? NorinPalette.darkCard : NorinPalette.lightCard,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(18),
              side: BorderSide(color: isDark ? NorinPalette.darkBorder : NorinPalette.lightBorder),
            ),
            child: InkWell(
              onTap: onTap,
              borderRadius: BorderRadius.circular(18),
              child: SizedBox(
                width: 78,
                height: 58,
                child: Center(
                  child: child ??
                      Text(
                        label,
                        style: tNumStyle.copyWith(fontSize: 22, fontWeight: FontWeight.w700),
                      ),
                ),
              ),
            ),
          ),
        ),
      );
    }

    return Column(
      children: [
        for (final row in const [
          ['1', '2', '3'],
          ['4', '5', '6'],
          ['7', '8', '9'],
        ])
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: row.map((d) => keyBtn(d, onTap: () => onDigit(d))).toList(),
          ),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (onBiometric != null)
              keyBtn(
                '',
                onTap: onBiometric,
                child: Icon(
                  Icons.fingerprint_rounded,
                  size: 28,
                  color: isDark ? NorinPalette.emeraldLight : NorinPalette.emeraldDark,
                ),
              )
            else
              const SizedBox(width: 90, height: 70),
            keyBtn('0', onTap: () => onDigit('0')),
            keyBtn(
              '',
              onTap: onBackspace,
              child: const Icon(Icons.backspace_outlined, size: 22),
            ),
          ],
        ),
      ],
    );
  }
}

class PinSetupScreen extends ConsumerStatefulWidget {
  const PinSetupScreen({super.key, this.isEditMode = false});

  final bool isEditMode;

  @override
  ConsumerState<PinSetupScreen> createState() => _PinSetupScreenState();
}

class _PinSetupScreenState extends ConsumerState<PinSetupScreen> {
  int _step = 0; // 0 = create, 1 = confirm, 2 = biometric prompt
  String _firstPin = '';
  String _currentPin = '';
  int _shakeNonce = 0;
  bool _saving = false;

  Future<void> _onDigit(String d) async {
    if (_saving || _step > 1 || _currentPin.length >= 4) return;
    setState(() => _currentPin += d);
    if (_currentPin.length < 4) return;

    if (_step == 0) {
      await Future<void>.delayed(const Duration(milliseconds: 110));
      if (!mounted) return;
      setState(() {
        _firstPin = _currentPin;
        _currentPin = '';
        _step = 1;
      });
      return;
    }

    // Step 1: confirm entered PIN
    if (_currentPin != _firstPin) {
      HapticFeedback.heavyImpact();
      showSnack(context, "PIN-kodlar mos kelmadi, qaytadan tering", error: true);
      setState(() {
        _firstPin = '';
        _currentPin = '';
        _step = 0;
        _shakeNonce++;
      });
      return;
    }

    setState(() => _saving = true);
    final lock = ref.read(biometricLockProvider);
    await ref.read(biometricLockProvider.notifier).setPinCode(_firstPin);
    if (!mounted) return;

    if (!widget.isEditMode && lock.biometricAvailable && !lock.enabled) {
      setState(() {
        _saving = false;
        _step = 2;
      });
      return;
    }

    showSnack(context, "PIN-kod saqlandi");
    if (widget.isEditMode && Navigator.of(context).canPop()) {
      Navigator.of(context).pop();
    } else {
      setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final lock = ref.watch(biometricLockProvider);
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final title = switch (_step) {
      0 => widget.isEditMode ? "Yangi 4 xonali PIN-kod" : "4 xonali PIN-kod yarating",
      1 => "PIN-kodni tasdiqlang",
      _ => "Barmoq izini yoqasizmi?",
    };
    final subtitle = switch (_step) {
      0 => "Ilovaga tezkor va xavfsiz kirish uchun",
      1 => "Yana bir marta xuddi shu 4 ta raqamni tering",
      _ => "Keyingi safar barmoq izi bilan darhol kirasiz",
    };

    return Scaffold(
      appBar: widget.isEditMode
          ? AppBar(
              title: const Text("PIN-kod sozlash", style: TextStyle(fontWeight: FontWeight.w800)),
            )
          : null,
      body: CosmicBackground(
        showBottomHorizonGlow: true,
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 18),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 380),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const GlowingSquircleEmblem(size: 76),
                    const SizedBox(height: 8),
                    AnimatedSwitcher(
                      duration: const Duration(milliseconds: 220),
                      child: Column(
                        key: ValueKey('pin_head_$_step'),
                        children: [
                          Text(
                            title,
                            textAlign: TextAlign.center,
                            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            subtitle,
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontSize: 13,
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 22),
                    if (_step < 2) ...[
                      TweenAnimationBuilder<double>(
                        key: ValueKey('setup_shake_$_shakeNonce'),
                        tween: Tween(begin: 0, end: _shakeNonce == 0 ? 0 : 1),
                        duration: const Duration(milliseconds: 360),
                        builder: (context, v, child) => Transform.translate(
                          offset: Offset(math.sin(v * math.pi * 4) * (1 - v) * 12, 0),
                          child: child,
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: List.generate(4, (i) {
                            final filled = i < _currentPin.length;
                            return AnimatedScale(
                              scale: filled ? 1.15 : 1.0,
                              duration: const Duration(milliseconds: 140),
                              curve: Curves.easeOutBack,
                              child: AnimatedContainer(
                                duration: const Duration(milliseconds: 150),
                                width: 16,
                                height: 16,
                                margin: const EdgeInsets.symmetric(horizontal: 10),
                                decoration: BoxDecoration(
                                  shape: BoxShape.circle,
                                  color: filled
                                      ? (isDark
                                          ? NorinPalette.emeraldLight
                                          : NorinPalette.emeraldDark)
                                      : Colors.transparent,
                                  border: Border.all(
                                    color: filled
                                        ? NorinPalette.magenta
                                        : (isDark
                                            ? NorinPalette.darkBorderGlow
                                            : NorinPalette.emeraldDark.withValues(alpha: 0.45)),
                                    width: 1.8,
                                  ),
                                ),
                              ),
                            );
                          }),
                        ),
                      ),
                      const SizedBox(height: 22),
                      _PinPad(
                        onDigit: _onDigit,
                        onBackspace: () {
                          if (_currentPin.isNotEmpty) {
                            setState(() => _currentPin = _currentPin.substring(0, _currentPin.length - 1));
                          } else if (_step == 1) {
                            setState(() {
                              _step = 0;
                              _firstPin = '';
                            });
                          }
                        },
                      ),
                      const SizedBox(height: 14),
                      if (widget.isEditMode && lock.hasPin)
                        TextButton(
                          onPressed: () async {
                            await ref.read(biometricLockProvider.notifier).setPinCode(null);
                            if (!context.mounted) return;
                            showSnack(context, "PIN-kod o'chirildi");
                            if (Navigator.of(context).canPop()) Navigator.of(context).pop();
                          },
                          child: const Text(
                            "PIN-kodni o'chirish",
                            style: TextStyle(color: NorinPalette.danger, fontWeight: FontWeight.w700),
                          ),
                        )
                      else if (!widget.isEditMode)
                        TextButton(
                          onPressed: () => ref.read(biometricLockProvider.notifier).markSetupCompleted(),
                          child: const Text("Keyinroq"),
                        ),
                    ] else ...[
                      const SizedBox(height: 8),
                      NeonPillButton(
                        onPressed: _saving
                            ? null
                            : () async {
                                setState(() => _saving = true);
                                final ok = await ref
                                    .read(biometricLockProvider.notifier)
                                    .setBiometricEnabled(true);
                                if (!context.mounted) return;
                                showSnack(
                                  context,
                                  ok ? "Otpechatka ham yoqildi" : "Tasdiqlanmadi, PIN faol qoldi",
                                  error: !ok,
                                );
                                await ref.read(biometricLockProvider.notifier).markSetupCompleted();
                              },
                        busy: _saving,
                        icon: Icons.fingerprint_rounded,
                        label: "Otpechatkani yoqish",
                      ),
                      const SizedBox(height: 10),
                      TextButton(
                        onPressed: () => ref.read(biometricLockProvider.notifier).markSetupCompleted(),
                        child: const Text("Keyinroq"),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
