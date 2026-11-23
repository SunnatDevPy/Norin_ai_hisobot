import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';

import '../api/api_client.dart';
import '../theme/app_theme.dart';
import '../version.dart';
import '../widgets/metric_cards.dart';
import '../widgets/norin_widgets.dart';

const MethodChannel _installerChannel = MethodChannel('uz.norinai.norin_ai_app/installer');

class AppUpdateInfo {
  const AppUpdateInfo({
    required this.version,
    required this.build,
    required this.full,
    required this.builtAt,
    required this.sizeBytes,
    required this.apkAvailable,
  });

  final String version;
  final int build;
  final String full;
  final String builtAt;
  final int sizeBytes;
  final bool apkAvailable;

  bool get hasUpdate => apkAvailable && build > kAppBuildNumber;

  factory AppUpdateInfo.fromJson(Map<String, dynamic> json) {
    return AppUpdateInfo(
      version: asStr(json['version'], kAppVersion),
      build: asInt(json['build'], kAppBuildNumber),
      full: asStr(json['full'], kAppFullVersion),
      builtAt: asStr(json['built_at']),
      sizeBytes: asInt(json['size_bytes']),
      apkAvailable: json['apk_available'] == true,
    );
  }
}

Future<AppUpdateInfo> checkForAppUpdate(ApiClient api) async {
  final raw = await api.get('/apk/version');
  return AppUpdateInfo.fromJson(asMap(raw));
}

Future<void> checkAndPromptUpdate(
  BuildContext context,
  ApiClient api, {
  bool silentIfLatest = true,
}) async {
  if (!Platform.isAndroid) {
    if (!silentIfLatest && context.mounted) {
      showSnack(context, "Avto-yangilash faqat Android qurilmada ishlaydi.");
    }
    return;
  }

  try {
    final info = await checkForAppUpdate(api);
    if (!context.mounted) return;
    if (info.hasUpdate) {
      await showUpdateAvailableDialog(context, api, info);
      return;
    }
    if (!silentIfLatest) {
      showSnack(
        context,
        "Sizda eng so'nggi versiya o'rnatilgan: v$kAppVersion (#$kAppBuildNumber)",
      );
    }
  } catch (e) {
    if (!silentIfLatest && context.mounted) {
      showSnack(context, ApiClient.extractError(e), error: true);
    }
  }
}

Future<void> showUpdateAvailableDialog(
  BuildContext context,
  ApiClient api,
  AppUpdateInfo info,
) async {
  final sizeMb = info.sizeBytes > 0
      ? '${(info.sizeBytes / (1024 * 1024)).toStringAsFixed(1)} MB'
      : '';
  final confirm = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: NorinPalette.emerald.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Icon(Icons.system_update_rounded, color: NorinPalette.emerald),
          ),
          const SizedBox(width: 10),
          const Expanded(
            child: Text("Yangi versiya mavjud!", style: TextStyle(fontSize: 18)),
          ),
        ],
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            "Joriy versiya: v$kAppVersion (build #$kAppBuildNumber)",
            style: TextStyle(color: Theme.of(ctx).colorScheme.onSurfaceVariant, fontSize: 13),
          ),
          const SizedBox(height: 4),
          Text(
            "Yangi versiya: v${info.version} (build #${info.build})",
            style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14.5),
          ),
          if (sizeMb.isNotEmpty || info.builtAt.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              [
                if (sizeMb.isNotEmpty) "Hajmi: $sizeMb",
                if (info.builtAt.isNotEmpty) "Sana: ${info.builtAt}",
              ].join(" • "),
              style: const TextStyle(fontSize: 12.5),
            ),
          ],
          const SizedBox(height: 12),
          const Text(
            "Ilova ichida avtomatik yuklab olinib o'rnatiladi. Ma'lumotlar va kirish sessiyangiz saqlanib qoladi.",
            style: TextStyle(fontSize: 12.5, height: 1.4),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx, false),
          child: const Text("Keyinroq"),
        ),
        FilledButton.icon(
          onPressed: () => Navigator.pop(ctx, true),
          icon: const Icon(Icons.download_rounded),
          label: const Text("Yangilash"),
        ),
      ],
    ),
  );

  if (confirm != true || !context.mounted) return;

  await showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => _InAppUpdateProgressDialog(api: api, info: info),
  );
}

class _InAppUpdateProgressDialog extends StatefulWidget {
  const _InAppUpdateProgressDialog({required this.api, required this.info});

  final ApiClient api;
  final AppUpdateInfo info;

  @override
  State<_InAppUpdateProgressDialog> createState() => _InAppUpdateProgressDialogState();
}

class _InAppUpdateProgressDialogState extends State<_InAppUpdateProgressDialog> {
  int _receivedBytes = 0;
  late int _totalBytes;
  bool _downloading = true;
  File? _downloadedFile;
  String _statusMessage = "Yangi versiya yuklab olinmoqda...";
  String? _error;

  @override
  void initState() {
    super.initState();
    _totalBytes = widget.info.sizeBytes;
    _startDownloadAndInstall();
  }

  Future<void> _startDownloadAndInstall() async {
    setState(() {
      _downloading = true;
      _error = null;
      _receivedBytes = 0;
      _statusMessage = "Yangi versiya yuklab olinmoqda...";
    });
    try {
      final dir = await getTemporaryDirectory();
      final target = File('${dir.path}/Sotuv_AI_v${widget.info.version}.apk');
      if (await target.exists()) {
        await target.delete();
      }
      await widget.api.downloadWithProgress(
        '/download/norin_ai.apk',
        target.path,
        onReceiveProgress: (received, total) {
          if (!mounted) return;
          setState(() {
            _receivedBytes = received;
            if (total > 0) _totalBytes = total;
          });
        },
      );
      final fileSize = await target.length();
      if (fileSize < 100 * 1024) {
        throw Exception("Yuklangan APK fayl to'liq emas ($fileSize bayt)");
      }
      if (!mounted) return;
      setState(() {
        _downloading = false;
        _downloadedFile = target;
        _statusMessage = "Yuklab olindi! O'rnatish oynasi ochilmoqda...";
      });
      await _triggerNativeInstall(target);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _downloading = false;
        _error = ApiClient.extractError(e);
      });
    }
  }

  Future<void> _triggerNativeInstall(File file) async {
    try {
      final res = await _installerChannel.invokeMethod<String>(
        'installApk',
        {'path': file.path},
      );
      if (!mounted) return;
      if (res == 'PERMISSION_REQUESTED') {
        setState(() {
          _statusMessage =
              "Telefon sozlamalarida «Sotuv AI» ilovasiga o'rnatish ruxsatini yoqing — qaytishingiz bilan o'rnatish avtomatik boshlanadi.";
        });
      } else {
        setState(() {
          _statusMessage = "Android o'rnatish oynasida «Yangilash (Update)» tugmasini bosing.";
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final progress = _totalBytes > 0 ? (_receivedBytes / _totalBytes).clamp(0.0, 1.0) : null;
    final recMb = (_receivedBytes / (1024 * 1024)).toStringAsFixed(1);
    final totMb = _totalBytes > 0 ? (_totalBytes / (1024 * 1024)).toStringAsFixed(1) : '?';

    return AlertDialog(
      title: Text(
        "Sotuv AI v${widget.info.version}",
        style: const TextStyle(fontWeight: FontWeight.w800),
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_error != null) ...[
            Text(
              _error!,
              style: const TextStyle(color: NorinPalette.danger, fontSize: 13),
            ),
          ] else ...[
            Text(_statusMessage, style: const TextStyle(fontSize: 13.5, height: 1.4)),
            const SizedBox(height: 14),
            LinearProgressIndicator(value: _downloading ? progress : 1.0),
            const SizedBox(height: 8),
            Text(
              _downloading
                  ? "$recMb MB / $totMb MB${progress != null ? ' (${(progress * 100).round()}%)' : ''}"
                  : "Tayyor ($totMb MB)",
              textAlign: TextAlign.end,
              style: tNumStyle.copyWith(fontSize: 12, fontWeight: FontWeight.w600),
            ),
          ],
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(_downloading ? "Yashirish" : "Yopish"),
        ),
        if (!_downloading && _error != null)
          FilledButton(
            onPressed: _startDownloadAndInstall,
            child: const Text("Qayta urinish"),
          ),
        if (!_downloading && _error == null && _downloadedFile != null)
          FilledButton(
            onPressed: () => _triggerNativeInstall(_downloadedFile!),
            child: const Text("O'rnatishni ochish"),
          ),
      ],
    );
  }
}
