import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_client.dart';
import '../../core/state/providers.dart';
import '../../core/theme/app_theme.dart';
import '../../core/widgets/norin_widgets.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _tgCtrl = TextEditingController();
  final _otpCtrl = TextEditingController();
  late final TextEditingController _urlCtrl;

  bool _codeSent = false;
  bool _busy = false;
  bool _showServerSettings = false;
  int _resendSeconds = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _urlCtrl = TextEditingController(text: ref.read(apiClientProvider).baseUrl);
  }

  @override
  void dispose() {
    _timer?.cancel();
    _tgCtrl.dispose();
    _otpCtrl.dispose();
    _urlCtrl.dispose();
    super.dispose();
  }

  void _startCooldown([int seconds = 60]) {
    _timer?.cancel();
    setState(() => _resendSeconds = seconds);
    _timer = Timer.periodic(const Duration(seconds: 1), (t) {
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

  Future<void> _applyServerUrlIfEdited() async {
    final url = _urlCtrl.text.trim();
    if (url.isNotEmpty) {
      await ref.read(apiClientProvider).setBaseUrl(url);
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
      await _applyServerUrlIfEdited();
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
      await _applyServerUrlIfEdited();
      await ref.read(authProvider.notifier).verifyOtp(
            telegramId: tgId,
            code: code,
            deviceName: 'Norin AI Android',
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
    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 460),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(
                      gradient: NorinPalette.heroGradient,
                      borderRadius: BorderRadius.circular(24),
                      boxShadow: [
                        BoxShadow(
                          color: NorinPalette.emerald.withValues(alpha: 0.25),
                          blurRadius: 24,
                          offset: const Offset(0, 10),
                        ),
                      ],
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: Colors.white.withValues(alpha: 0.16),
                                borderRadius: BorderRadius.circular(16),
                              ),
                              child: const Icon(
                                Icons.analytics_rounded,
                                color: Colors.white,
                                size: 30,
                              ),
                            ),
                            const Spacer(),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                              decoration: BoxDecoration(
                                color: Colors.white.withValues(alpha: 0.16),
                                borderRadius: BorderRadius.circular(999),
                              ),
                              child: const Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(Icons.verified_user_rounded, size: 14, color: Colors.white),
                                  SizedBox(width: 5),
                                  Text(
                                    "SaaS V1",
                                    style: TextStyle(
                                      color: Colors.white,
                                      fontSize: 12,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 18),
                        const Text(
                          "Norin AI Hisobot",
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 26,
                            fontWeight: FontWeight.w800,
                            letterSpacing: -0.4,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          "Savdo, kassa, mijozlar qarzdorligi, AI chek tahlili va filiallar boshqaruvi.",
                          style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.9),
                            fontSize: 13.5,
                            height: 1.4,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(
                            _codeSent ? "Tasdiqlash kodini kiriting" : "Tizimga kirish",
                            style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            _codeSent
                                ? "Telegram botga yuborilgan 6 xonali kodni kiriting (5 daqiqa amal qiladi)."
                                : "Telegram ID raqamingizni kiriting. Super Admin uchun tasdiqlash kodi bot orqali keladi.",
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.onSurfaceVariant,
                              height: 1.4,
                            ),
                          ),
                          const SizedBox(height: 18),
                          TextField(
                            controller: _tgCtrl,
                            enabled: !_busy && !_codeSent,
                            keyboardType: TextInputType.number,
                            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                            decoration: const InputDecoration(
                              labelText: "Telegram ID",
                              hintText: "Masalan: 5649321700",
                              prefixIcon: Icon(Icons.badge_outlined),
                            ),
                          ),
                          if (_codeSent) ...[
                            const SizedBox(height: 14),
                            TextField(
                              controller: _otpCtrl,
                              enabled: !_busy,
                              keyboardType: TextInputType.number,
                              maxLength: 6,
                              style: const TextStyle(
                                fontSize: 22,
                                fontWeight: FontWeight.w800,
                                letterSpacing: 6,
                              ),
                              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                              decoration: const InputDecoration(
                                labelText: "6 xonali OTP kod",
                                hintText: "000000",
                                counterText: "",
                                prefixIcon: Icon(Icons.lock_outline_rounded),
                              ),
                              onSubmitted: (_) => _verifyCode(),
                            ),
                          ],
                          const SizedBox(height: 18),
                          FilledButton.icon(
                            onPressed: _busy ? null : (_codeSent ? _verifyCode : _requestCode),
                            icon: _busy
                                ? const SizedBox(
                                    width: 18,
                                    height: 18,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2.2,
                                      color: Colors.white,
                                    ),
                                  )
                                : Icon(_codeSent ? Icons.login_rounded : Icons.send_rounded),
                            label: Padding(
                              padding: const EdgeInsets.symmetric(vertical: 14),
                              child: Text(
                                _codeSent ? "Kirish" : "Kod olish",
                                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
                              ),
                            ),
                          ),
                          if (_codeSent) ...[
                            const SizedBox(height: 10),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                TextButton.icon(
                                  onPressed: _busy
                                      ? null
                                      : () => setState(() {
                                            _codeSent = false;
                                            _otpCtrl.clear();
                                          }),
                                  icon: const Icon(Icons.arrow_back_rounded, size: 18),
                                  label: const Text("ID ni o'zgartirish"),
                                ),
                                TextButton(
                                  onPressed: (_busy || _resendSeconds > 0) ? null : _requestCode,
                                  child: Text(
                                    _resendSeconds > 0
                                        ? "Qayta yuborish ($_resendSeconds s)"
                                        : "Qayta kod olish",
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 14),
                  Card(
                    child: Column(
                      children: [
                        ListTile(
                          leading: const Icon(Icons.dns_outlined),
                          title: const Text(
                            "Server manzili",
                            style: TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                          ),
                          subtitle: Text(
                            _urlCtrl.text,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontSize: 12),
                          ),
                          trailing: Icon(
                            _showServerSettings ? Icons.expand_less : Icons.expand_more,
                          ),
                          onTap: () => setState(() => _showServerSettings = !_showServerSettings),
                        ),
                        if (_showServerSettings)
                          Padding(
                            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                TextField(
                                  controller: _urlCtrl,
                                  keyboardType: TextInputType.url,
                                  decoration: const InputDecoration(
                                    labelText: "API Base URL",
                                    hintText: "http://46.8.194.206:8000/api/v1",
                                  ),
                                ),
                                const SizedBox(height: 10),
                                Row(
                                  children: [
                                    Expanded(
                                      child: OutlinedButton(
                                        onPressed: () async {
                                          _urlCtrl.text = ApiConfig.defaultBaseUrl;
                                          await ref
                                              .read(apiClientProvider)
                                              .setBaseUrl(ApiConfig.defaultBaseUrl);
                                          if (context.mounted) {
                                            showSnack(context, "Standart server tiklandi");
                                          }
                                        },
                                        child: const Text("Standart"),
                                      ),
                                    ),
                                    const SizedBox(width: 10),
                                    Expanded(
                                      child: FilledButton.tonal(
                                        onPressed: () async {
                                          await _applyServerUrlIfEdited();
                                          if (context.mounted) {
                                            showSnack(context, "Server manzili saqlandi");
                                          }
                                        },
                                        child: const Text("Saqlash"),
                                      ),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                      ],
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
