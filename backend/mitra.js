import 'dotenv/config';
import { createClientFromEnvironment } from '@mitralab.io/functions-sdk';

let client;
let initialization;

export async function getMitra() {
  client ??= createClientFromEnvironment();
  initialization ??= client.init().catch((error) => {
    initialization = undefined;
    throw error;
  });
  await initialization;
  return client;
}
