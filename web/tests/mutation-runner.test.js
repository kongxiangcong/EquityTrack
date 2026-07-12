import test from "node:test"
import assert from "node:assert/strict"
import {createMutationRunner} from "../src/mutation-runner.js"

test("ambiguous response loss replays the same invocation without duplicating the mutation",async()=>{
  const calls=[];let first=true
  const runner=createMutationRunner(async(payload,invocationId)=>{calls.push({payload,invocationId});if(first){first=false;const error=new Error("lost response");error.resultUnknown=true;throw error}return{version_no:1}},()=>"stable-invocation")
  const payload={operation:"create",anchors:[{exact_price_decimal:"82.33"}]}
  await assert.rejects(runner.run(payload),error=>error.resultUnknown)
  assert.equal(runner.hasUnknownResult(),true)
  assert.deepEqual(await runner.run(payload),{version_no:1})
  assert.deepEqual(calls.map(call=>call.invocationId),["stable-invocation","stable-invocation"])
})

test("known validation failure releases the invocation and uncertain result blocks a different command",async()=>{
  let sequence=0
  const runner=createMutationRunner(async()=>{sequence++;const error=new Error(sequence===1?"invalid":"unknown");error.resultUnknown=sequence!==1;throw error},()=>`inv-${sequence}`)
  await assert.rejects(runner.run({operation:"revise"}),error=>!error.resultUnknown)
  assert.equal(runner.hasUnknownResult(),false)
  await assert.rejects(runner.run({operation:"delete"}),error=>error.resultUnknown)
  await assert.rejects(runner.run({operation:"restore"}),/COMMAND_RESULT_UNKNOWN_RETRY_SAME/)
})
