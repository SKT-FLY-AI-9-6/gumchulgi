import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import 'feed.dart';

class SettingsController extends AsyncNotifier<AppSettings> {
  @override
  Future<AppSettings> build() => ref.read(apiProvider).getSettings();

  Future<void> setFilter(bool on) => _put(
      (s) => s.copyWith(filterOn: on));

  Future<void> setAutoSkip(bool on) => _put(
      (s) => s.copyWith(autoSkip: on));

  Future<void> _put(AppSettings Function(AppSettings) f) async {
    final cur = state.value ??
        const AppSettings(filterOn: true, autoSkip: false);
    final next = f(cur);
    state = AsyncData(next);
    try {
      state = AsyncData(await ref.read(apiProvider).putSettings(next));
      // 노출 규칙이 서버에 확정된 뒤에 피드를 다시 불러야 한다 —
      // optimistic 시점에 부르면 옛 설정으로 계산된 피드를 받는다.
      ref.invalidate(feedProvider);
    } catch (e) {
      state = AsyncData(cur);
      rethrow;
    }
  }
}

final settingsProvider =
    AsyncNotifierProvider<SettingsController, AppSettings>(
        SettingsController.new);
