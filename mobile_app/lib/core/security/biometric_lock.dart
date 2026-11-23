import 'dart:io';

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
  });

  final bool initialized;
  final bool biometricAvailable;
  final bool enabled;
  final String? pinCode;
  final bool locked;

  bool get hasPin => pinCode != null && pinCode!.length == 4;
  bool get hasAnyLock => enabled || hasPin;

  BiometricLockState copyWith({
    bool? initialized,
    bool? biometricAvailable,
    bool? enabled,
    String? pinCode,
    bool clearPin = false,
    bool? locked,
  }) {
    return BiometricLockState(
      initialized: initialized ?? this.initialized,
      biometricAvailable: biometricAvailable ?? this.biometricAvailable,
      enabled: enabled ?? this.enabled,
      pinCode: clearPin ? null : (pinCode ?? this.pinCode),
      locked: locked ?? this.locked,
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

  DateTime? _pausedAt;

  Future<void> init() async {
    final available = await NativeBridge.canAuthenticateBiometric();
    final bioRaw = await _storage.read(key: _kBioKey);
    final pinRaw = await _storage.read(key: _kPinKey);
    final enabled = bioRaw == '1' && available;
    final hasPin = pinRaw != null && pinRaw.length == 4;
    state = BiometricLockState(
      initialized: true,
      biometricAvailable: available,
      enabled: enabled,
      pinCode: hasPin ? pinRaw : null,
      locked: enabled || hasPin,
    );
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
      state = state.copyWith(biometricAvailable: true, enabled: true, locked: false);
      return true;
    }
    await _storage.write(key: _kBioKey, value: '0');
    state = state.copyWith(enabled: false, locked: false);
    return true;
  }

  Future<void> setPinCode(String? pin) async {
    if (pin == null || pin.trim().isEmpty) {
      await _storage.delete(key: _kPinKey);
      state = state.copyWith(clearPin: true, locked: false);
      return;
    }
    final clean = pin.trim();
    await _storage.write(key: _kPinKey, value: clean);
    state = state.copyWith(pinCode: clean, locked: false);
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
        setState(() => _pin = '');
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
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: List.generate(4, (i) {
                          final filled = i < _pin.length;
                          return Container(
                            width: 16,
                            height: 16,
                            margin: const EdgeInsets.symmetric(horizontal: 10),
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color: filled ? NorinPalette.emeraldLight : Colors.transparent,
                              border: Border.all(
                                color: filled ? NorinPalette.magenta : NorinPalette.darkBorderGlow,
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
                          );
                        }),
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
    Widget keyBtn(String label, {VoidCallback? onTap, Widget? child}) {
      return Padding(
        padding: const EdgeInsets.all(6),
        child: Material(
          color: NorinPalette.darkCard,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
            side: const BorderSide(color: NorinPalette.darkBorder),
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
                child: const Icon(Icons.fingerprint_rounded, size: 28, color: NorinPalette.emeraldLight),
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
