import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import 'exposure.dart';
import 'feed.dart';
import 'settings.dart';

class AuthController extends AsyncNotifier<User?> {
  @override
  Future<User?> build() async {
    final api = ref.read(apiProvider);
    api.onUnauthorized = () async {
      await api.clearToken();
      state = const AsyncData(null);
    };
    final t = await api.loadToken();
    if (t == null) return null;
    try {
      return await api.me();
    } catch (e) {
      if (e is DioException && e.response?.statusCode == 401) {
        await api.clearToken();
      }
      return null;
    }
  }

  void _invalidateUserState() {
    ref.invalidate(feedProvider);
    ref.invalidate(settingsProvider);
    ref.invalidate(exposureProvider);
  }

  void clearFailure() {
    if (state.hasError) state = const AsyncData(null);
  }

  Future<void> login(String email, String pw) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(
      () => ref.read(apiProvider).login(email, pw),
    );
    if (!state.hasError) _invalidateUserState();
  }

  Future<void> signup(String email, String pw, String nickname) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(
      () => ref.read(apiProvider).signup(email, pw, nickname),
    );
    if (!state.hasError) _invalidateUserState();
  }

  Future<void> logout() async {
    await ref.read(apiProvider).clearToken();
    state = const AsyncData(null);
    _invalidateUserState();
  }
}

final authProvider = AsyncNotifierProvider<AuthController, User?>(
  AuthController.new,
);
