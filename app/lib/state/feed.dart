import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';

class FeedController extends AsyncNotifier<List<FeedVideo>> {
  int? _cursor;
  bool _end = false, _loading = false;

  @override
  Future<List<FeedVideo>> build() async {
    _cursor = null; _end = false;
    final (vids, next) = await ref.read(apiProvider).feed();
    _cursor = next; _end = next == null || vids.isEmpty;
    return vids;
  }

  Future<void> loadMore() async {
    if (_end || _loading) return;
    _loading = true;
    try {
      final (vids, next) =
          await ref.read(apiProvider).feed(cursor: _cursor);
      _cursor = next; _end = next == null || vids.isEmpty;
      state = AsyncData([...state.value ?? [], ...vids]);
    } finally {
      _loading = false;
    }
  }

  Future<void> refreshAll() async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(build);
  }

  Future<void> toggleLike(int id) async {
    final list = state.value;
    if (list == null) return;
    final i = list.indexWhere((v) => v.id == id);
    if (i < 0) return;
    final api = ref.read(apiProvider);
    final (count, liked) = list[i].likedByMe
        ? await api.unlike(id) : await api.like(id);
    final copy = [...list];
    copy[i] = list[i].copyWith(likeCount: count, likedByMe: liked);
    state = AsyncData(copy);
  }
}

final feedProvider =
    AsyncNotifierProvider<FeedController, List<FeedVideo>>(FeedController.new);
