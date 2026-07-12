export function createMutationRunner(send, newInvocationId=()=>crypto.randomUUID()){
  let pending=null
  return {
    async run(payload){
      const key=JSON.stringify(payload)
      if(pending&&pending.key!==key){const error=new Error("COMMAND_RESULT_UNKNOWN_RETRY_SAME");error.resultUnknown=true;throw error}
      pending??={key,payload,invocationId:newInvocationId()}
      try{const result=await send(pending.payload,pending.invocationId);pending=null;return result}
      catch(error){if(!error.resultUnknown)pending=null;throw error}
    },
    hasUnknownResult(){return pending!==null},
  }
}
