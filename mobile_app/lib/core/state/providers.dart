import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';

final apiClientProvider = Provider<ApiClient>((ref) => ApiClient());

final themeModeProvider = StateProvider<ThemeMode>((ref) => ThemeMode.dark);

enum AuthStage { loading, unauthenticated, authenticated }

class AuthState {
  const AuthState({
    required this.stage,
    this.telegramId,
    this.role,
    this.selectedTenantId = 1,
  });

  final AuthStage stage;
  final int? telegramId;
  final String? role;
  final int selectedTenantId;

  bool get isSuperAdmin => role == 'super_admin';

  AuthState copyWith({
    AuthStage? stage,
    int? telegramId,
    String? role,
    int? selectedTenantId,
  }) {
    return AuthState(
      stage: stage ?? this.stage,
      telegramId: telegramId ?? this.telegramId,
      role: role ?? this.role,
      selectedTenantId: selectedTenantId ?? this.selectedTenantId,
    );
  }
}

class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier(this._api) : super(const AuthState(stage: AuthStage.loading));

  final ApiClient _api;

  Future<void> bootstrap() async {
    await _api.init();
    if (!_api.isAuthenticated) {
      state = const AuthState(stage: AuthStage.unauthenticated);
      return;
    }
    try {
      final me = await _api.get('/auth/me') as Map<String, dynamic>;
      final role = me['role'] as String;
      final baseTid = (me['tenant_id'] as num).toInt();
      final effectiveTid =
          role == 'super_admin' ? (_api.selectedTenantId ?? baseTid) : baseTid;
      if (role != 'super_admin') {
        await _api.setSelectedTenant(baseTid);
      }
      state = AuthState(
        stage: AuthStage.authenticated,
        telegramId: (me['telegram_id'] as num).toInt(),
        role: role,
        selectedTenantId: effectiveTid,
      );
    } catch (_) {
      await _api.clearSession();
      state = const AuthState(stage: AuthStage.unauthenticated);
    }
  }

  Future<void> _applyTokenResponse(Map<String, dynamic> res) async {
    final tid = (res['tenant_id'] as num).toInt();
    final role = res['role'] as String;
    final effectiveTid =
        role == 'super_admin' ? (_api.selectedTenantId ?? tid) : tid;
    await _api.saveSession(
      accessToken: res['access_token'] as String,
      refreshToken: res['refresh_token'] as String,
      role: role,
      telegramId: 0,
      tenantId: effectiveTid,
    );
    if (role != 'super_admin') {
      await _api.setSelectedTenant(tid);
    }
    try {
      final me = await _api.get('/auth/me') as Map<String, dynamic>;
      final tgId = (me['telegram_id'] as num).toInt();
      await _api.saveSession(
        accessToken: res['access_token'] as String,
        refreshToken: res['refresh_token'] as String,
        role: role,
        telegramId: tgId,
        tenantId: effectiveTid,
      );
      state = AuthState(
        stage: AuthStage.authenticated,
        telegramId: tgId,
        role: role,
        selectedTenantId: effectiveTid,
      );
    } catch (_) {
      state = AuthState(
        stage: AuthStage.authenticated,
        role: role,
        selectedTenantId: effectiveTid,
      );
    }
  }

  Future<void> requestOtp(int telegramId) async {
    await _api.post('/auth/request-code', data: {'telegram_id': telegramId});
  }

  Future<void> verifyOtp({
    required int telegramId,
    required String code,
    String deviceName = 'Sotuv AI Android',
  }) async {
    final res = await _api.post(
      '/auth/verify-code',
      data: {
        'telegram_id': telegramId,
        'code': code.trim(),
        'device_name': deviceName,
      },
    ) as Map<String, dynamic>;
    final tid = (res['tenant_id'] as num).toInt();
    final role = res['role'] as String;
    final effectiveTid =
        role == 'super_admin' ? (_api.selectedTenantId ?? tid) : tid;
    await _api.saveSession(
      accessToken: res['access_token'] as String,
      refreshToken: res['refresh_token'] as String,
      role: role,
      telegramId: telegramId,
      tenantId: effectiveTid,
    );
    if (role != 'super_admin') {
      await _api.setSelectedTenant(tid);
    }
    state = AuthState(
      stage: AuthStage.authenticated,
      telegramId: telegramId,
      role: role,
      selectedTenantId: effectiveTid,
    );
  }

  Future<void> loginWithCode({
    required String code,
    String deviceName = 'Sotuv AI Android',
  }) async {
    final res = await _api.post(
      '/auth/login-code',
      data: {
        'code': code.trim(),
        'device_name': deviceName,
      },
    ) as Map<String, dynamic>;
    await _applyTokenResponse(res);
  }

  Future<Map<String, dynamic>> startTelegramTicket({
    String deviceName = 'Sotuv AI Android',
  }) async {
    final res = await _api.post(
      '/auth/telegram-ticket',
      data: {'device_name': deviceName},
    ) as Map<String, dynamic>;
    return res;
  }

  Future<bool> pollTelegramTicket({
    required String ticket,
    String deviceName = 'Sotuv AI Android',
  }) async {
    final res = await _api.post(
      '/auth/telegram-poll',
      data: {
        'ticket': ticket,
        'device_name': deviceName,
      },
    ) as Map<String, dynamic>;
    final status = res['status']?.toString() ?? 'pending';
    if (status == 'approved') {
      await _applyTokenResponse(res);
      return true;
    }
    if (status == 'expired') {
      throw Exception("Kirish havolasi muddati tugagan. Qaytadan bosing.");
    }
    return false;
  }

  Future<void> selectTenant(int tenantId) async {
    if (!state.isSuperAdmin) return;
    await _api.setSelectedTenant(tenantId);
    state = state.copyWith(selectedTenantId: tenantId);
  }

  Future<void> logout() async {
    try {
      await _api.post('/auth/logout');
    } catch (_) {}
    await _api.clearSession();
    state = const AuthState(stage: AuthStage.unauthenticated);
  }
}

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  return AuthNotifier(ref.read(apiClientProvider));
});

final selectedPeriodProvider = StateProvider<String>((ref) => 'today');
final chartPeriodProvider = StateProvider<String>((ref) => '30');

final dashboardSummaryProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  ref.watch(authProvider.select((s) => s.selectedTenantId));
  final period = ref.watch(selectedPeriodProvider);
  final data = await ref.read(apiClientProvider).get('/dashboard/summary', query: {'period': period});
  return Map<String, dynamic>.from(data as Map);
});

final dashboardChartsProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  ref.watch(authProvider.select((s) => s.selectedTenantId));
  final period = ref.watch(chartPeriodProvider);
  final data = await ref.read(apiClientProvider).get('/dashboard/charts', query: {'period': period, 'top': 5});
  return Map<String, dynamic>.from(data as Map);
});

final productsProvider = FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  ref.watch(authProvider.select((s) => s.selectedTenantId));
  final data = await ref.read(apiClientProvider).get('/products');
  return (data as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
});

final clientsProvider = FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  ref.watch(authProvider.select((s) => s.selectedTenantId));
  final data = await ref.read(apiClientProvider).get('/clients');
  return (data as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
});

final todayProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  ref.watch(authProvider.select((s) => s.selectedTenantId));
  final data = await ref.read(apiClientProvider).get('/today');
  return Map<String, dynamic>.from(data as Map);
});

final settingsProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  ref.watch(authProvider.select((s) => s.selectedTenantId));
  final data = await ref.read(apiClientProvider).get('/settings');
  return Map<String, dynamic>.from(data as Map);
});

final adminAnalyticsProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  final data = await ref.read(apiClientProvider).get('/admin/analytics');
  return Map<String, dynamic>.from(data as Map);
});

final adminTenantsProvider = FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  final data = await ref.read(apiClientProvider).get('/admin/tenants');
  return (data as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
});

void invalidateOperationalData(WidgetRef ref) {
  ref.invalidate(dashboardSummaryProvider);
  ref.invalidate(dashboardChartsProvider);
  ref.invalidate(clientsProvider);
  ref.invalidate(todayProvider);
  ref.invalidate(productsProvider);
  ref.invalidate(settingsProvider);
}
