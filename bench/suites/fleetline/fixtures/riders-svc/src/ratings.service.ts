export class RatingsService {
  average(stars: number[]): number {
    return stars.reduce((a, b) => a + b, 0) / Math.max(stars.length, 1);
  }
}
