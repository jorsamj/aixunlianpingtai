export function createActionRegistry() {
  const handlers = new Map();
  return {
    register(name, handler) {
      if (handlers.has(name)) {
        throw new Error(`动作已注册：${name}`);
      }
      if (typeof handler !== 'function') {
        throw new TypeError(`动作处理器必须是函数：${name}`);
      }
      handlers.set(name, handler);
      return handler;
    },
    invoke(name, context) {
      const handler = handlers.get(name);
      if (!handler) {
        throw new Error(`动作未注册：${name}`);
      }
      return handler(context);
    },
    has: name => handlers.has(name)
  };
}


export const actionRegistry = createActionRegistry();
export const registerAction = (name, handler) => actionRegistry.register(name, handler);
export const invokeAction = (name, context) => actionRegistry.invoke(name, context);

