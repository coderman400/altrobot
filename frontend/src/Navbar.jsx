import React from 'react'
import { Github } from 'lucide-react'
const Navbar = () => {
  return (
    <div className='py-6 px-8 flex flex-row justify-between'>
        <p className='font-libre text-lg'>Altrobot</p>
        <a href='https://github.com/coderman400/altrobot' target='_blank'><Github size={30} /></a>
    </div>
  )
}

export default Navbar