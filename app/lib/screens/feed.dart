import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../state/exposure.dart';
import '../state/feed.dart';
import '../state/settings.dart';
import '../theme.dart';
import '../widgets/settings_sheet.dart';
import '../widgets/video_page.dart';

class FeedScreen extends ConsumerStatefulWidget {
  const FeedScreen({super.key});
  @override
  ConsumerState<FeedScreen> createState() => _FeedState();
}

class _FeedState extends ConsumerState<FeedScreen> {
  final _page = PageController();
  final _watch = Stopwatch();
  int _current = 0;

  @override
  void initState() {
    super.initState();
    _watch.start();
  }

  void _sendEvent(FeedVideo v) {
    final s = _watch.elapsed.inMilliseconds / 1000.0;
    _watch..reset()..start();
    if (s < 0.5) return; // 스쳐 지나간 페이지는 무시
    ref.read(apiProvider)
        .sendEvent(v.id, s.clamp(0, 600), v.variant)
        .then((e) => ref.read(exposureProvider.notifier).update(e))
        .catchError((_) {});
  }

  @override
  void deactivate() {
    final vids = ref.read(feedProvider).value;
    if (vids != null && _current < vids.length) _sendEvent(vids[_current]);
    super.deactivate();
  }

  @override
  Widget build(BuildContext context) {
    // 설정이 바뀌면 노출 규칙이 달라지므로 피드 재로드
    ref.listen(settingsProvider, (prev, next) {
      if (prev?.value != null && next.value != null &&
          (prev!.value!.filterOn != next.value!.filterOn ||
           prev.value!.autoSkip != next.value!.autoSkip)) {
        ref.read(feedProvider.notifier).refreshAll();
      }
    });
    final feed = ref.watch(feedProvider);
    return Stack(children: [
      feed.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Column(
            mainAxisSize: MainAxisSize.min, children: [
          const Text('피드를 불러오지 못했습니다'),
          TextButton(
              onPressed: () => ref.read(feedProvider.notifier).refreshAll(),
              child: const Text('다시 시도')),
        ])),
        data: (vids) => vids.isEmpty
            ? const Center(child: Text('아직 영상이 없습니다',
                style: TextStyle(color: AppColors.sub)))
            : PageView.builder(
                controller: _page, scrollDirection: Axis.vertical,
                itemCount: vids.length,
                onPageChanged: (i) {
                  _sendEvent(vids[_current]);
                  setState(() => _current = i);
                  if (i >= vids.length - 2) {
                    ref.read(feedProvider.notifier).loadMore();
                  }
                },
                itemBuilder: (_, i) => VideoPage(
                    key: ValueKey('${vids[i].id}-${vids[i].variant}'),
                    video: vids[i], active: i == _current))),
      // 우상단 필터 버튼 (목업 ①)
      Positioned(top: 48, right: 12, child: IconButton(
          icon: const Icon(Icons.filter_alt_outlined, size: 28),
          onPressed: () => showSettingsSheet(context))),
    ]);
  }
}
