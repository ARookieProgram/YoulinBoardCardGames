import type { CountMap, TingMap } from "../types/domain";

/**
 * 麻将听牌判定（纯逻辑，不碰 DB / socket）。
 *
 * 这里只依赖座位上的三样数据，因此用最小接口描述入参：gamemgr 直接把 `GameSeat` 传进来，
 * 门禁的行为冒烟（`tools/lib/smoke.mjs`）则用 `buildSeat` 临时造一个同样形状的对象。
 */
export interface TingPaiSeat {
  /** 手牌。 */
  holds: number[];
  /** 手牌计数表。 */
  countMap: CountMap;
  /** 听牌表，`checkTingPai` 会把可和的牌写进来。 */
  tingMap: TingMap;
}

/**
 * 逐个试牌，把能和的牌写进 `seatData.tingMap`。
 *
 * @param seatData 手上牌的数据（会被就地修改：临时加牌判定后再撤销）。
 * @param begin 起始牌 id（含）。
 * @param end 结束牌 id（不含）。
 */
export function checkTingPai(seatData: TingPaiSeat, begin: number, end: number): void {
	for(var i = begin; i < end; ++i){
		//如果这牌已经在和了，就不用检查了
		if(seatData.tingMap[i] != null){
			continue;
		}
		//将牌加入到计数中
		var old: number | undefined = seatData.countMap[i];
		if(old == null){
			old = 0;
			seatData.countMap[i] = 1;
		}
		else{
			seatData.countMap[i] ++;
		}

		seatData.holds.push(i);
		//逐个判定手上的牌
		var ret = checkCanHu(seatData);
		if(ret){
			//平胡 0番
			seatData.tingMap[i] = {
				pattern:"normal",
                fan:0
			};
		}

		//搞完以后，撤消刚刚加的牌
		seatData.countMap[i] = old;
		seatData.holds.pop();
	}
}

var kanzi: number[] = [];
var record = false;
function debugRecord(pai: number): void {
	if(record){
		kanzi.push(pai);
	}
}

function matchSingle(seatData: TingPaiSeat, selected: number): boolean {
	//分开匹配 A-2,A-1,A
	var matched = true;
	var v = selected % 9;
	if(v < 2){
		matched = false;
	}
	else{
		for(var i = 0; i < 3; ++i){
			var t = selected - 2 + i;
			var cc: number | undefined = seatData.countMap[t];
			if(cc == null){
				matched = false;
				break;
			}
			if(cc == 0){
				matched = false;
				break;
			}
		}
	}


	//匹配成功，扣除相应数值
	if(matched){
		seatData.countMap[selected - 2] --;
		seatData.countMap[selected - 1] --;
		seatData.countMap[selected] --;
		var ret = checkSingle(seatData);
		seatData.countMap[selected - 2] ++;
		seatData.countMap[selected - 1] ++;
		seatData.countMap[selected] ++;
		if(ret == true){
			debugRecord(selected - 2);
			debugRecord(selected - 1);
			debugRecord(selected);
			return true;
		}
	}

	//分开匹配 A-1,A,A + 1
	matched = true;
	if(v < 1 || v > 7){
		matched = false;
	}
	else{
		for(var i = 0; i < 3; ++i){
			var t = selected - 1 + i;
			var cc: number | undefined = seatData.countMap[t];
			if(cc == null){
				matched = false;
				break;
			}
			if(cc == 0){
				matched = false;
				break;
			}
		}
	}

	//匹配成功，扣除相应数值
	if(matched){
		seatData.countMap[selected - 1] --;
		seatData.countMap[selected] --;
		seatData.countMap[selected + 1] --;
		var ret = checkSingle(seatData);
		seatData.countMap[selected - 1] ++;
		seatData.countMap[selected] ++;
		seatData.countMap[selected + 1] ++;
		if(ret == true){
			debugRecord(selected - 1);
			debugRecord(selected);
			debugRecord(selected + 1);
			return true;
		}
	}


	//分开匹配 A,A+1,A + 2
	matched = true;
	if(v > 6){
		matched = false;
	}
	else{
		for(var i = 0; i < 3; ++i){
			var t = selected + i;
			var cc: number | undefined = seatData.countMap[t];
			if(cc == null){
				matched = false;
				break;
			}
			if(cc == 0){
				matched = false;
				break;
			}
		}
	}

	//匹配成功，扣除相应数值
	if(matched){
		seatData.countMap[selected] --;
		seatData.countMap[selected + 1] --;
		seatData.countMap[selected + 2] --;
		var ret = checkSingle(seatData);
		seatData.countMap[selected] ++;
		seatData.countMap[selected + 1] ++;
		seatData.countMap[selected + 2] ++;
		if(ret == true){
			debugRecord(selected);
			debugRecord(selected + 1);
			debugRecord(selected + 2);
			return true;
		}
	}
	return false;
}

function checkSingle(seatData: TingPaiSeat): boolean {
	var holds = seatData.holds;
	var selected = -1;
	var c = 0;
	for(var i = 0; i < holds.length; ++i){
		var pai = holds[i];
		c = seatData.countMap[pai];
		if(c != 0){
			selected = pai;
			break;
		}
	}
	//如果没有找到剩余牌，则表示匹配成功了
	if(selected == -1){
		return true;
	}
	//否则，进行匹配
	if(c == 3){
		//直接作为一坎
		seatData.countMap[selected] = 0;
		debugRecord(selected);
		debugRecord(selected);
		debugRecord(selected);
		var ret = checkSingle(seatData);
		//立即恢复对数据的修改
		seatData.countMap[selected] = c;
		if(ret == true){
			return true;
		}
	}
	else if(c == 4){
		//直接作为一坎
		seatData.countMap[selected] = 1;
		debugRecord(selected);
		debugRecord(selected);
		debugRecord(selected);
		var ret = checkSingle(seatData);
		//立即恢复对数据的修改
		seatData.countMap[selected] = c;
		//如果作为一坎能够把牌匹配完，直接返回TRUE。
		if(ret == true){
			return true;
		}
	}

	//按单牌处理
	return matchSingle(seatData,selected);
}

/**
 * 遍历每一种将牌，判断剩下的牌能否拆成 3N。
 *
 * 注意：与原实现一样，**没有实现七对**（门禁的 smoke 用例把这一限制钉住了）；
 * 也因为没有显式 `return false`，无解时返回 `undefined`——调用方只做真值判断。
 *
 * @param seatData 手牌数据。
 * @returns 能和时 true，否则 undefined。
 */
function checkCanHu(seatData: TingPaiSeat): boolean | undefined {
	for(var k in seatData.countMap){
		var key = parseInt(k);
		var c = seatData.countMap[key];
		if(c < 2){
			continue;
		}
		//如果当前牌大于等于２，则将它选为将牌
		seatData.countMap[key] -= 2;
		//逐个判定剩下的牌是否满足　３Ｎ规则,一个牌会有以下几种情况
		//1、0张，则不做任何处理
		//2、2张，则只可能是与其它牌形成匹配关系
		//3、3张，则可能是单张形成 A-2,A-1,A  A-1,A,A+1  A,A+1,A+2，也可能是直接成为一坎
		//4、4张，则只可能是一坎+单张
		kanzi = [];
		var ret = checkSingle(seatData);
		seatData.countMap[key] += 2;
		if(ret){
			//kanzi.push(k);
			//kanzi.push(k);
			//console.log(kanzi);
			return true;
		}
	}
}

/*
console.log(Date.now());
//检查筒子
checkTingPai(seatData,0,9);
//检查条子
checkTingPai(seatData,9,18);
//检查万字
checkTingPai(seatData,18,27);
console.log(Date.now());

for(k in seatData.tingMap){
	console.log(nameMap[k]);	
}
*/

/**
 * 牌 id 转花色：0 筒 / 1 条 / 2 万，范围外返回 undefined（与原实现一致）。
 *
 * @param pai 牌 id。
 * @returns 花色索引。
 */
export function getMJType(pai: number): number | undefined {
      //参数名是 pai，下面的判断必须读同一个变量；写成 id 会抛 ReferenceError。
      //gamemgr_xlch.ts / gamemgr_xzdd.ts 里各有一份同逻辑的本地实现，此处保持等价。
      if(pai >= 0 && pai < 9){
          //筒
          return 0;
      }
      else if(pai >= 9 && pai < 18){
          //条
          return 1;
      }
      else if(pai >= 18 && pai < 27){
          //万
          return 2;
      }
      return undefined;
}
