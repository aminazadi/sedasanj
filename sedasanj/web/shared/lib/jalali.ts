const BREAKS = [
  -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262,
  2324, 2394, 2456, 3178,
];

function div(value: number, divisor: number): number {
  return Math.trunc(value / divisor);
}

function mod(value: number, divisor: number): number {
  return value - Math.trunc(value / divisor) * divisor;
}

function jalaliCalendar(year: number): { leap: number; gregorianYear: number; march: number } {
  const gregorianYear = year + 621;
  let leapJ = -14;
  let previousBreak = BREAKS[0];
  let jump = 0;

  if (year < previousBreak || year >= BREAKS[BREAKS.length - 1]) {
    throw new RangeError(`Invalid Jalali year: ${year}`);
  }

  for (let index = 1; index < BREAKS.length; index += 1) {
    const currentBreak = BREAKS[index];
    jump = currentBreak - previousBreak;
    if (year < currentBreak) break;
    leapJ += div(jump, 33) * 8 + div(mod(jump, 33), 4);
    previousBreak = currentBreak;
  }

  let yearsAfterBreak = year - previousBreak;
  leapJ += div(yearsAfterBreak, 33) * 8 + div(mod(yearsAfterBreak, 33) + 3, 4);
  if (mod(jump, 33) === 4 && jump - yearsAfterBreak === 4) leapJ += 1;

  const leapG = div(gregorianYear, 4) - div((div(gregorianYear, 100) + 1) * 3, 4) - 150;
  const march = 20 + leapJ - leapG;

  if (jump - yearsAfterBreak < 6) {
    yearsAfterBreak = yearsAfterBreak - jump + div(jump + 4, 33) * 33;
  }
  let leap = mod(mod(yearsAfterBreak + 1, 33) - 1, 4);
  if (leap === -1) leap = 4;

  return { leap, gregorianYear, march };
}

function gregorianToDayNumber(year: number, month: number, day: number): number {
  let result =
    div((year + div(month - 8, 6) + 100100) * 1461, 4) +
    div(153 * mod(month + 9, 12) + 2, 5) +
    day -
    34840408;
  result -= div(div(year + 100100 + div(month - 8, 6), 100) * 3, 4) - 752;
  return result;
}

function dayNumberToGregorian(dayNumber: number): GregorianDate {
  let value = 4 * dayNumber + 139361631;
  value += div(div(4 * dayNumber + 183187720, 146097) * 3, 4) * 4 - 3908;
  const offset = div(mod(value, 1461), 4) * 5 + 308;
  const day = div(mod(offset, 153), 5) + 1;
  const month = mod(div(offset, 153), 12) + 1;
  const year = div(value, 1461) - 100100 + div(8 - month, 6);
  return { year, month, day };
}

function jalaliToDayNumber(year: number, month: number, day: number): number {
  const calendar = jalaliCalendar(year);
  return (
    gregorianToDayNumber(calendar.gregorianYear, 3, calendar.march) +
    (month - 1) * 31 -
    div(month, 7) * (month - 7) +
    day -
    1
  );
}

export interface JalaliDate {
  year: number;
  month: number;
  day: number;
}

export interface GregorianDate {
  year: number;
  month: number;
  day: number;
}

export function toJalali(year: number, month: number, day: number): JalaliDate {
  const dayNumber = gregorianToDayNumber(year, month, day);
  const gregorian = dayNumberToGregorian(dayNumber);
  let jalaliYear = gregorian.year - 621;
  const calendar = jalaliCalendar(jalaliYear);
  const firstFarvardin = gregorianToDayNumber(gregorian.year, 3, calendar.march);
  let offset = dayNumber - firstFarvardin;

  if (offset >= 0) {
    if (offset <= 185) {
      return {
        year: jalaliYear,
        month: 1 + div(offset, 31),
        day: mod(offset, 31) + 1,
      };
    }
    offset -= 186;
  } else {
    jalaliYear -= 1;
    offset += 179;
    if (calendar.leap === 1) offset += 1;
  }

  return {
    year: jalaliYear,
    month: 7 + div(offset, 30),
    day: mod(offset, 30) + 1,
  };
}

export function toGregorian(year: number, month: number, day: number): GregorianDate {
  return dayNumberToGregorian(jalaliToDayNumber(year, month, day));
}

export function jalaliMonthLength(year: number, month: number): number {
  if (month <= 6) return 31;
  if (month <= 11) return 30;
  return jalaliCalendar(year).leap === 0 ? 30 : 29;
}
