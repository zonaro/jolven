import 'package:flutter_test/flutter_test.dart';
import 'package:jolven_flutter/src/retroachievements_page.dart';

void main() {
  test('parses official user game progress response without inventing unlocks', () {
    final result = AchievementProgress.parse({
      'Title': 'Demo Homebrew',
      'ConsoleName': 'NES',
      'NumAchievements': 10,
      'NumAwardedToUser': 4,
      'NumAwardedToUserHardcore': 2,
    });
    expect(result.gameTitle, 'Demo Homebrew');
    expect(result.earned, 4);
    expect(result.hardcore, 2);
    expect(result.total, 10);
  });

  test('malformed/empty API result cannot be shown as a success', () {
    expect(() => AchievementProgress.parse({}), throwsFormatException);
    expect(() => AchievementProgress.parse({
      'Title': 'Invalid',
      'NumAchievements': -1,
    }), throwsFormatException);
  });

  test('invalid key/game ID are rejected before network', () async {
    const client = AchievementProgressClient();
    expect(
      () => client.load(username: '', apiKey: 'secret', gameId: 1),
      throwsFormatException,
    );
    expect(
      () => client.load(username: 'someone', apiKey: '', gameId: 1),
      throwsFormatException,
    );
    expect(
      () => client.load(username: 'someone', apiKey: 'secret', gameId: 0),
      throwsFormatException,
    );
  });
}
