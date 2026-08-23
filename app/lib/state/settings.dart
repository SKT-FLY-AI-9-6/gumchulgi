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
      // 서버에 확정된 뒤에 피드에 반영한다 (optimistic 시점에 하면 옛
      // 설정으로 계산된 피드를 받을 수 있다).
      if (next.autoSkip != cur.autoSkip) {
        ref.invalidate(feedProvider); // 숨김 규칙이 바뀌므로 재조회
      } else if (next.filterOn != cur.filterOn) {
        // 보던 영상 그 자리에서 원본 <-> 보정본만 교체
        ref.read(feedProvider.notifier).applyFilter(next.filterOn);
      }
    } catch (e) {
      state = AsyncData(cur);
      rethrow;
    }
  }
}

final settingsProvider =
    AsyncNotifierProvider<SettingsController, AppSettings>(
        SettingsController.new);
