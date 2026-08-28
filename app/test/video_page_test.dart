import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gumchulgi_app/api/models.dart';
import 'package:gumchulgi_app/widgets/video_page.dart';

void main() {
  testWidgets('영상 영역 탭으로 일시정지와 재생 상태를 전환한다', (tester) async {
    final video = FeedVideo(
      id: 99,
      title: 'tap test',
      uploaderNickname: 'tester',
      risk: 'safe',
      variant: 'original',
      streamUrl: '/videos/99/stream?variant=original',
      thumbUrl: '/videos/99/thumb',
      durationS: 20,
      likeCount: 0,
      viewCount: 0,
      likedByMe: false,
      stimulus: const {},
    );

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          home: Scaffold(
            body: VideoPage(video: video, active: true, preload: false),
          ),
        ),
      ),
    );

    final tapLayer = find.byKey(const ValueKey('video-playback-toggle-99'));
    expect(tapLayer, findsOneWidget);
    expect(find.byIcon(Icons.play_arrow_rounded), findsNothing);

    await tester.tap(tapLayer);
    await tester.pump();
    expect(find.byIcon(Icons.play_arrow_rounded), findsOneWidget);

    await tester.tap(tapLayer);
    await tester.pump();
    expect(find.byIcon(Icons.play_arrow_rounded), findsNothing);
  });
}
