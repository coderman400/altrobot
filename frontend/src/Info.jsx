import React from 'react'

const Info = () => {
  return (
    <div className='flex flex-col justify-between items-center w-full my-16 text-text'>
        <div className='w-1/2 text-2xl font-libre '>
            <p>What does this tool do?</p>
            <p className='text-[1.05rem] mt-4'>
                It will automatically extract all the images from your .docx file in order, generate alt texts using AI and compress them to &lt;100kb. <br></br><br></br>It will also optimize GIFs, but you may need to check them manually. (not very good at it)
            </p>
        </div>
        
    </div>
  )
}

export default Info