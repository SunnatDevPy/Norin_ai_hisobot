import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/security/biometric_lock.dart';
import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/version.dart';
import '../../core/widgets/metric_cards.dart';
import '../../core/widgets/norin_widgets.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> with WidgetsBindingObserver {
  final _quickCodeCtrl = TextEditingController();
  final _tgCtrl = TextEditingController();
  final _otpCtrl = TextEditingController();

  String? _activeTicket;
  String? _activeBotUrl;
  Timer? _pollTimer;
  bool _pollingInFlight = false;

  bool _codeSent = false;
  bool _busy = false;
  bool _showAdvanced = false;
  int _resendSeconds = 0;
  Timer? _resendTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _pollTimer?.cancel();
    _resendTimer?.cancel();
    _quickCodeCtrl.dispose();
    _tgCtrl.dispose();
    _otpCtrl.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && _activeTicket != null) {
      _pollTicketOnce();
    }
  }

  void _startCooldown([int seconds = 60]) {
    _resendTimer?.cancel();
    setState(() => _resendSeconds = seconds);
    _resendTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) {
        t.cancel();
        return;
      }
      if (_resendSeconds <= 1) {
        t.cancel();
        setState(() => _resendSeconds = 0);
      } else {
        setState(() => _resendSeconds--);
      }
    });
  }

  Future<void> _startOneTapTelegram() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final res = await ref.read(authProvider.notifier).startTelegramTicket();
      final ticket = asStr(res['ticket']);
      final tgUri = asStr(res['tg_uri']);
      final botUrl = asStr(res['bot_url']);
      if (ticket.isEmpty) throw Exception("Ticket yaratilmadi");

      setState(() {
        _activeTicket = ticket;
        _activeBotUrl = botUrl;
      });
      _startPollingLoop();

      var opened = false;
      if (tgUri.isNotEmpty) {
        opened = await NativeBridge.openExternalUrl(tgUri);
      }
      if (!opened && botUrl.isNotEmpty) {
        opened = await NativeBridge.openExternalUrl(botUrl);
      }
      if (!opened && mounted) {
        showSnack(
          context,
          "Telegram avtomatik ochilmadi. Botda /apk yozib 6 xonali kod oling.",
          error: true,
        );
      }
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _startPollingLoop() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 2), (_) => _pollTicketOnce());
  }

  void _cancelTicketPolling() {
    _pollTimer?.cancel();
    setState(() {
      _activeTicket = null;
      _activeBotUrl = null;
    });
  }

  Future<void> _pollTicketOnce() async {
    final ticket = _activeTicket;
    if (ticket == null || _pollingInFlight || !mounted) return;
    _pollingInFlight = true;
    try {
      final approved = await ref.read(authProvider.notifier).pollTelegramTicket(ticket: ticket);
      if (approved) {
        _pollTimer?.cancel();
        if (mounted) setState(() => _activeTicket = null);
      }
    } catch (e) {
      _pollTimer?.cancel();
      if (mounted) {
        setState(() {
          _activeTicket = null;
          _activeBotUrl = null;
        });
        showSnack(context, ApiClient.extractError(e), error: true);
      }
    } finally {
      _pollingInFlight = false;
    }
  }

  Future<void> _loginWithCodeOnly() async {
    final code = _quickCodeCtrl.text.trim();
    if (code.length < 6) {
      showSnack(context, "Botdagi 6 xonali kirish kodini kiriting", error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(authProvider.notifier).loginWithCode(code: code);
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _requestCode() async {
    final tgId = int.tryParse(_tgCtrl.text.trim());
    if (tgId == null || tgId <= 0) {
      showSnack(context, "Telegram ID raqamini to'g'ri kiriting", error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(authProvider.notifier).requestOtp(tgId);
      if (!mounted) return;
      setState(() => _codeSent = true);
      _startCooldown(60);
      showSnack(context, "Agar ruxsat bo'lsa, 6 xonali kod Telegram botga yuborildi.");
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _verifyCode() async {
    final tgId = int.tryParse(_tgCtrl.text.trim());
    final code = _otpCtrl.text.trim();
    if (tgId == null || code.length < 6) {
      showSnack(context, "6 xonali tasdiqlash kodini kiriting", error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(authProvider.notifier).verifyOtp(
            telegramId: tgId,
            code: code,
            deviceName: 'Sotuv AI Android',
          );
    } catch (e) {
      if (mounted) showSnack(context, ApiClient.extractError(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final waitingTg = _activeTicket != null;

    return Scaffold(
      body: CosmicBackground(
        showBottomHorizonGlow: true,
        child: SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Center(child: GlowingSquircleEmblem(size: 102)),
                    const SizedBox(height: 4),
                    Text(
                      "Sotuv AI",
                      textAlign: TextAlign.center,
                      style: theme.textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.w900,
                        letterSpacing: -0.5,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      "Kichik biznes va uyda sotuvchilar uchun aqlli hisob • v$kAppVersion",
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 20),
                    SpotlightHeroCard(
                      padding: const EdgeInsets.all(20),
                      glowColor: NorinPalette.emeraldLight,
                      accentColor: NorinPalette.indigo,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Row(
                            children: [
                              Container(
                                width: 8,
                                height: 8,
                                decoration: const BoxDecoration(
                                  color: NorinPalette.magenta,
                                  shape: BoxShape.circle,
                                ),
                              ),
                              const SizedBox(width: 8),
                              Text(
                                "Tizimga kirish",
                                style: theme.textTheme.titleMedium?.copyWith(
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 14),
                          if (waitingTg) ...[
                            Container(
                              padding: const EdgeInsets.all(14),
                              decoration: BoxDecoration(
                                color: NorinPalette.emerald.withValues(alpha: 0.16),
                                borderRadius: BorderRadius.circular(16),
                                border: Border.all(
                                  color: NorinPalette.emeraldLight.withValues(alpha: 0.5),
                                ),
                              ),
                              child: Column(
                                children: [
                                  const Row(
                                    children: [
                                      SizedBox(
                                        width: 18,
                                        height: 18,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2.2,
                                          color: NorinPalette.emeraldLight,
                                        ),
                                      ),
                                      SizedBox(width: 12),
                                      Expanded(
                                        child: Text(
                                          "Telegram botda START tugmasini bosing — ilova avtomatik ulanadi...",
                                          style: TextStyle(
                                            fontSize: 13,
                                            fontWeight: FontWeight.w700,
                                            height: 1.35,
                                          ),
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 10),
                                  Row(
                                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                    children: [
                                      if (_activeBotUrl != null)
                                        TextButton.icon(
                                          onPressed: () => NativeBridge.openExternalUrl(_activeBotUrl!),
                                          icon: const Icon(Icons.open_in_new_rounded, size: 16),
                                          label: const Text("Telegramni ochish"),
                                        ),
                                      TextButton(
                                        onPressed: _cancelTicketPolling,
                                        child: const Text("Bekor qilish"),
                                      ),
                                    ],
                                  ),
                                ],
                              ),
                            ),
                          ] else
                            NeonPillButton(
                              onPressed: _busy ? null : _startOneTapTelegram,
                              busy: _busy,
                              icon: Icons.telegram_rounded,
                              label: "Telegram orqali 1-bosishda kirish",
                            ),
                          const SizedBox(height: 16),
                          Row(
                            children: [
                              const Expanded(child: Divider()),
                              Padding(
                                padding: const EdgeInsets.symmetric(horizontal: 10),
                                child: Text(
                                  "yoki botdagi kod bilan",
                                  style: TextStyle(
                                    fontSize: 11.5,
                                    color: theme.colorScheme.onSurfaceVariant,
                                  ),
                                ),
                              ),
                              const Expanded(child: Divider()),
                            ],
                          ),
                          const SizedBox(height: 14),
                          Row(
                            children: [
                              Expanded(
                                child: TextField(
                                  controller: _quickCodeCtrl,
                                  enabled: !_busy,
                                  keyboardType: TextInputType.number,
                                  maxLength: 6,
                                  textAlign: TextAlign.center,
                                  style: tNumStyle.copyWith(
                                    fontSize: 19,
                                    fontWeight: FontWeight.w800,
                                    letterSpacing: 5,
                                  ),
                                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                                  decoration: const InputDecoration(
                                    labelText: "6 xonali /apk kod",
                                    hintText: "••••••",
                                    counterText: "",
                                    prefixIcon: Icon(Icons.key_rounded),
                                  ),
                                  onChanged: (v) {
                                    if (v.trim().length == 6 && !_busy) {
                                      _loginWithCodeOnly();
                                    }
                                  },
                                  onSubmitted: (_) => _loginWithCodeOnly(),
                                ),
                              ),
                              const SizedBox(width: 10),
                              SizedBox(
                                height: 52,
                                child: FilledButton.tonal(
                                  onPressed: _busy ? null : _loginWithCodeOnly,
                                  child: const Text("Kirish", style: TextStyle(fontWeight: FontWeight.w800)),
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 14),
                    Card(
                      child: Column(
                        children: [
                          ListTile(
                            leading: const Icon(Icons.key_outlined, color: NorinPalette.emeraldLight),
                            title: const Text(
                              "Telegram ID orqali kod olish",
                              style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13.5),
                            ),
                            subtitle: const Text(
                              "Qo'shimcha kirish usuli",
                              style: TextStyle(fontSize: 11.5),
                            ),
                            trailing: Icon(
                              _showAdvanced ? Icons.expand_less : Icons.expand_more,
                            ),
                            onTap: () => setState(() => _showAdvanced = !_showAdvanced),
                          ),
                          if (_showAdvanced)
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.stretch,
                                children: [
                                  const Divider(),
                                  const SizedBox(height: 12),
                                  TextField(
                                    controller: _tgCtrl,
                                    enabled: !_busy && !_codeSent,
                                    keyboardType: TextInputType.number,
                                    inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                                    decoration: const InputDecoration(
                                      labelText: "Telegram ID",
                                      hintText: "Telegram ID raqamingiz",
                                      prefixIcon: Icon(Icons.badge_outlined),
                                    ),
                                  ),
                                  if (_codeSent) ...[
                                    const SizedBox(height: 10),
                                    TextField(
                                      controller: _otpCtrl,
                                      enabled: !_busy,
                                      keyboardType: TextInputType.number,
                                      maxLength: 6,
                                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                                      decoration: const InputDecoration(
                                        labelText: "6 xonali OTP kod",
                                        counterText: "",
                                        prefixIcon: Icon(Icons.lock_outline_rounded),
                                      ),
                                      onSubmitted: (_) => _verifyCode(),
                                    ),
                                  ],
                                  const SizedBox(height: 10),
                                  Row(
                                    children: [
                                      Expanded(
                                        child: FilledButton.tonal(
                                          onPressed:
                                              _busy ? null : (_codeSent ? _verifyCode : _requestCode),
                                          child: Text(_codeSent ? "Kirish" : "Kod olish"),
                                        ),
                                      ),
                                      if (_codeSent) ...[
                                        const SizedBox(width: 8),
                                        TextButton(
                                          onPressed: (_busy || _resendSeconds > 0) ? null : _requestCode,
                                          child: Text(_resendSeconds > 0 ? "$_resendSeconds s" : "Qayta"),
                                        ),
                                      ],
                                    ],
                                  ),
                                ],
                              ),
                            ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      "Telegram botda /apk buyrug'i orqali ham 6 xonali kirish kodini olishingiz mumkin.",
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodySmall?.copyWith(
                        fontSize: 11.5,
                        color: theme.colorScheme.onSurfaceVariant,
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
