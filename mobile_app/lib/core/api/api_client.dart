import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

class ApiConfig {
  static const defaultBaseUrl = 'https://minishop.okaposai.uz/api/v1';
}

class ApiClient {
  ApiClient()
      : _storage = const FlutterSecureStorage(
          aOptions: AndroidOptions(encryptedSharedPreferences: true),
        ),
        _dio = Dio(
          BaseOptions(
            baseUrl: ApiConfig.defaultBaseUrl,
            connectTimeout: const Duration(seconds: 12),
            receiveTimeout: const Duration(seconds: 40),
            sendTimeout: const Duration(seconds: 40),
          ),
        ) {
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) async {
          options.baseUrl = _baseUrl;
          if (_accessToken != null && _accessToken!.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $_accessToken';
          }
          if (_selectedTenantId != null) {
            options.headers['X-Tenant-Id'] = '$_selectedTenantId';
          }
          handler.next(options);
        },
        onError: (err, handler) async {
          final status = err.response?.statusCode;
          final path = err.requestOptions.path;
          final alreadyRetried = err.requestOptions.extra['_retried'] == true;
          if (status == 401 &&
              !alreadyRetried &&
              !isPublicAuthPath(path) &&
              await _refreshAccessToken()) {
            err.requestOptions.extra['_retried'] = true;
            err.requestOptions.headers['Authorization'] = 'Bearer $_accessToken';
            try {
              final clone = await _dio.fetch(err.requestOptions);
              return handler.resolve(clone);
            } catch (_) {}
          }
          handler.next(err);
        },
      ),
    );
  }

  final FlutterSecureStorage _storage;
  final Dio _dio;

  String _baseUrl = ApiConfig.defaultBaseUrl;
  String? _accessToken;
  String? _refreshToken;
  String? _role;
  int? _telegramId;
  int _baseTenantId = 1;
  int? _selectedTenantId;
  Completer<bool>? _refreshCompleter;

  static const _publicAuthPaths = <String>{
    '/auth/refresh',
    '/auth/request-code',
    '/auth/verify-code',
    '/auth/login-code',
    '/auth/telegram-ticket',
    '/auth/telegram-poll',
  };

  /// Returns true only for unauthenticated auth endpoints that must NOT trigger token refresh.
  static bool isPublicAuthPath(String path) {
    final clean = path.split('?').first;
    return _publicAuthPaths.any((p) => clean.endsWith(p));
  }

  String get baseUrl => _baseUrl;
  String? get role => _role;
  int? get telegramId => _telegramId;
  int get baseTenantId => _baseTenantId;
  int? get selectedTenantId => _selectedTenantId;
  bool get isAuthenticated =>
      (_accessToken != null && _accessToken!.isNotEmpty) ||
      (_refreshToken != null && _refreshToken!.isNotEmpty);
  bool get isSuperAdmin => _role == 'super_admin';

  Future<void> init() async {
    _baseUrl = ApiConfig.defaultBaseUrl;
    _accessToken = await _storage.read(key: 'access_token');
    _refreshToken = await _storage.read(key: 'refresh_token');
    _role = await _storage.read(key: 'role');
    final tidRaw = await _storage.read(key: 'telegram_id');
    _telegramId = tidRaw != null ? int.tryParse(tidRaw) : null;
    final baseTidRaw = await _storage.read(key: 'tenant_id');
    _baseTenantId = (baseTidRaw != null ? int.tryParse(baseTidRaw) : null) ?? 1;
    // Always default to own filial on startup (Super Admin #1; enforced server-side for tenants)
    _selectedTenantId = _baseTenantId;
    await _storage.delete(key: 'selected_tenant_id');
    _dio.options.baseUrl = _baseUrl;
  }

  Future<void> setBaseUrl(String url) async {
    // Backend endpoint is locked internally for security and privacy.
    _baseUrl = ApiConfig.defaultBaseUrl;
    _dio.options.baseUrl = _baseUrl;
  }

  Future<void> setSelectedTenant(int tenantId) async {
    _selectedTenantId = tenantId;
  }

  Future<void> saveSession({
    required String accessToken,
    required String refreshToken,
    required String role,
    required int telegramId,
    required int tenantId,
  }) async {
    _accessToken = accessToken;
    _refreshToken = refreshToken;
    _role = role;
    _telegramId = telegramId;
    _baseTenantId = tenantId;
    _selectedTenantId ??= tenantId;
    await _storage.write(key: 'access_token', value: accessToken);
    await _storage.write(key: 'refresh_token', value: refreshToken);
    await _storage.write(key: 'role', value: role);
    await _storage.write(key: 'telegram_id', value: '$telegramId');
    await _storage.write(key: 'tenant_id', value: '$tenantId');
  }

  Future<void> clearSession() async {
    _accessToken = null;
    _refreshToken = null;
    _role = null;
    _telegramId = null;
    _baseTenantId = 1;
    _selectedTenantId = 1;
    await _storage.delete(key: 'access_token');
    await _storage.delete(key: 'refresh_token');
    await _storage.delete(key: 'role');
    await _storage.delete(key: 'telegram_id');
    await _storage.delete(key: 'tenant_id');
  }

  Future<bool> _refreshAccessToken() async {
    if (_refreshToken == null || _refreshToken!.isEmpty) return false;
    if (_refreshCompleter != null) return _refreshCompleter!.future;
    final completer = Completer<bool>();
    _refreshCompleter = completer;
    try {
      final refreshDio = Dio(
        BaseOptions(
          baseUrl: _baseUrl,
          connectTimeout: const Duration(seconds: 12),
          receiveTimeout: const Duration(seconds: 20),
        ),
      );
      final resp = await refreshDio.post(
        '/auth/refresh',
        data: {'refresh_token': _refreshToken},
      );
      final data = resp.data as Map<String, dynamic>;
      _accessToken = data['access_token'] as String;
      _refreshToken = data['refresh_token'] as String;
      await _storage.write(key: 'access_token', value: _accessToken);
      await _storage.write(key: 'refresh_token', value: _refreshToken);
      completer.complete(true);
      return true;
    } on DioException catch (e) {
      final code = e.response?.statusCode;
      if (code == 401 || code == 403) {
        await clearSession();
      }
      completer.complete(false);
      return false;
    } catch (_) {
      completer.complete(false);
      return false;
    } finally {
      _refreshCompleter = null;
    }
  }

  static String extractError(Object error) {
    if (error is DioException) {
      final data = error.response?.data;
      if (data is Map && data['detail'] != null) {
        return data['detail'].toString();
      }
      if (error.type == DioExceptionType.connectionTimeout ||
          error.type == DioExceptionType.receiveTimeout ||
          error.type == DioExceptionType.sendTimeout ||
          error.type == DioExceptionType.connectionError) {
        return "Tizim bilan aloqa yo'q. Internetni tekshiring.";
      }
      final code = error.response?.statusCode;
      if (code != null) {
        return "So'rov bajarilmadi (kod: $code).";
      }
      return "Aloqa xatoligi yuz berdi. Qaytadan urinib ko'ring.";
    }
    var msg = error.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
    msg = msg.replaceAll(RegExp(r'https?://\S+'), '[tizim]');
    return msg.trim().isEmpty ? "Xatolik yuz berdi." : msg.trim();
  }

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) async {
    final resp = await _dio.get(path, queryParameters: query);
    return resp.data;
  }

  Future<dynamic> post(String path, {dynamic data}) async {
    final resp = await _dio.post(path, data: data);
    return resp.data;
  }

  Future<dynamic> patch(String path, {dynamic data}) async {
    final resp = await _dio.patch(path, data: data);
    return resp.data;
  }

  Future<dynamic> put(String path, {dynamic data}) async {
    final resp = await _dio.put(path, data: data);
    return resp.data;
  }

  Future<dynamic> delete(String path) async {
    final resp = await _dio.delete(path);
    return resp.data;
  }

  Future<dynamic> uploadFile(
    String path,
    String filePath, {
    String? caption,
  }) async {
    final form = FormData.fromMap({
      'file': await MultipartFile.fromFile(filePath),
      if (caption != null && caption.trim().isNotEmpty) 'caption': caption.trim(),
    });
    final resp = await _dio.post(path, data: form);
    return resp.data;
  }

  Future<void> downloadWithProgress(
    String path,
    String savePath, {
    void Function(int received, int total)? onReceiveProgress,
  }) async {
    await _dio.download(
      path,
      savePath,
      onReceiveProgress: onReceiveProgress,
      options: Options(receiveTimeout: const Duration(minutes: 5)),
    );
  }

  Future<File> downloadExcelFile(String path, String filename, {Map<String, dynamic>? query}) async {
    final dir = await getTemporaryDirectory();
    final safeName = filename.replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '_');
    final file = File('${dir.path}/$safeName');
    final resp = await _dio.get<List<int>>(
      path,
      queryParameters: query,
      options: Options(responseType: ResponseType.bytes),
    );
    await file.writeAsBytes(resp.data ?? <int>[], flush: true);
    return file;
  }

  Future<void> openOrShareExcel(
    String path,
    String filename, {
    Map<String, dynamic>? query,
    bool share = false,
  }) async {
    final file = await downloadExcelFile(path, filename, query: query);
    if (share) {
      await Share.shareXFiles([XFile(file.path)], text: 'Sotuv AI: $filename');
    } else {
      await OpenFilex.open(file.path);
    }
  }
}
