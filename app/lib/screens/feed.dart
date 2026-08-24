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
import '../widgets/warning_banner.dart';

class FeedScreen extends ConsumerStatefulWidget {
  const FeedScreen({super.key});
  @override
  ConsumerState<FeedScreen> createState() => _FeedState();
}

class _FeedState extends ConsumerState<FeedScreen> with WidgetsBindingObserver {
  final _page = PageController();
  final _watch = Stopwatch();
  int _current = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _watch.start();
    // 홈에 다시 들어왔을 때 이전 조회가 비어 있었다면(업로드 처리 전 등)
    // 캐시된 빈 목록을 그대로 보여주지 말고 다시 불러온다.
    Future.microtask(() {
      if (!mounted) return;
      final cached = ref.read(feedProvider).value;
      if (cached != null && cached.isEmpty) {
        ref.read(feedProvider.notifier).refreshAll();
      }
    });
  }

  void _sendEvent(FeedVideo v) {
    final s = _watch.elapsed.inMilliseconds / 1000.0;
    _watch..reset()..start();
    if (s < 0.5) return; // 스쳐 지나간 페이지는 무시
    final exposure = ref.read(exposureProvider.notifier);
    ref.read(apiProvider)
        .sendEvent(v.id, s.clamp(0, 600), v.variant)
        .then((e) => exposure.update(e))
        .catchError((_) {});
  }

  @override
  void deactivate() {
    final vids = ref.read(feedProvider).value;
    if (vids != null && _current < vids.length) _sendEvent(vids[_current]);
    super.deactivate();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final vids = ref.read(feedProvider).value;
    if (state == AppLifecycleState.paused) {
      if (vids != null && _current < vids.length) _sendEvent(vids[_current]);
      _watch.stop();
    } else if (state == AppLifecycleState.resumed) {
      _watch..reset()..start();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _page.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // 설정이 바뀌면 시청 기록을 마감하고 인덱스를 리셋한다.
    // 피드 재로드 자체는 SettingsController 가 서버 PUT 확정 후
    // feedProvider 를 invalidate 하는 것으로 수행된다 (레이스 방지).
    ref.listen(settingsProvider, (prev, next) {
      if (prev?.value == null || next.value == null) return;
      final filterChanged = prev!.value!.filterOn != next.value!.filterOn;
      final skipChanged = prev.value!.autoSkip != next.value!.autoSkip;
      if (!filterChanged && !skipChanged) return;
      // 이전 variant 의 시청 시간을 먼저 마감한다 (원본 시청만 노출 집계).
      final vids = ref.read(feedProvider).value;
      if (vids != null && _current < vids.length) _sendEvent(vids[_current]);
      _watch..reset()..start();
      if (skipChanged) {
        // 피드가 재조회되므로 처음으로
        setState(() => _current = 0);
        if (_page.hasClients) _page.jumpToPage(0);
      }
      // 필터 ON/OFF 만 바뀐 경우는 보던 자리에서 스트림만 교체된다.
    });
    final filterOn = ref.watch(settingsProvider).value?.filterOn ?? true;
    final topPad = MediaQuery.paddingOf(context).top;
    final feed = ref.watch(feedProvider);
    return Container(color: Colors.black,
        padding: EdgeInsets.only(top: topPad),
        child: Stack(children: [
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
            ? RefreshIndicator(
                onRefresh: () => ref.read(feedProvider.notifier).refreshAll(),
                child: ListView(children: [
                  SizedBox(
                    height: MediaQuery.sizeOf(context).height * .7,
                    child: Center(child: Column(
                        mainAxisSize: MainAxisSize.min, children: [
                      const Text('아직 영상이 없습니다',
                          style: TextStyle(color: AppColors.sub)),
                      const SizedBox(height: 4),
                      const Text('업로드한 영상은 검출·보정이 끝나면 표시됩니다',
                          style: TextStyle(color: AppColors.sub, fontSize: 12)),
                      TextButton.icon(
                          onPressed: () =>
                              ref.read(feedProvider.notifier).refreshAll(),
                          icon: const Icon(Icons.refresh),
                          label: const Text('새로고침')),
                    ])),
                  ),
                ]))
            : PageView.builder(
                controller: _page, scrollDirection: Axis.vertical,
                allowImplicitScrolling: true,
                itemCount: vids.length,
                onPageChanged: (i) {
                  _sendEvent(vids[_current]);
                  setState(() => _current = i);
                  if (i >= vids.length - 2) {
                    ref.read(feedProvider.notifier).loadMore();
                  }
                },
                // 키를 id 로만 잡아 variant 전환 시 페이지가 재생성되지
                // 않고 VideoPage 내부에서 컨트롤러만 교체되게 한다.
                itemBuilder: (_, i) => VideoPage(
                    key: ValueKey(vids[i].id),
                    video: vids[i], active: i == _current))),
      // 우상단 필터 버튼 (목업 ①)
      Positioned(top: 8, right: 12, child: IconButton(
          tooltip: filterOn ? '보호 필터 ON' : '보호 필터 OFF',
          icon: Icon(filterOn ? Icons.filter_alt : Icons.filter_alt_outlined,
              size: 28, color: filterOn ? AppColors.blue : AppColors.amber),
          onPressed: () => showSettingsSheet(context))),
      // 경고 배너 (목업 ④)
      const WarningBanner(),
    ]));
  }
}
